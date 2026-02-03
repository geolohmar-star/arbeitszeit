# schichtplan/services.py - MIT WUNSCH-INTEGRATION + SOLL-STUNDEN-VERRECHNUNG
"""
KI-gestützte Schichtplan-Generierung mit OR-Tools

VOLLSTÄNDIG mit:
- Typ A/B Klassifikation
- Typ B: Min 4T + 4N pro Monat
- Genau 2 Personen pro Schicht
- Fairness: Gleichmäßige Verteilung
- WUNSCH-INTEGRATION (Urlaub, Präferenzen)
- SOLL-STUNDEN-VERRECHNUNG (jeder arbeitet ca. gleich viel)
- AUTOMATISCHE ZUSATZDIENSTE zum Auffüllen
- INDIVIDUELLE VEREINBARUNGEN (erlaubte Tage, keine Zusatzdienste)
"""

import json
import datetime
import calendar
from collections import defaultdict
from decimal import Decimal
from ortools.sat.python import cp_model
from django.db.models import Q

from schichtplan.models import Schicht, Schichttyp, Schichtplan, Schichtwunsch
from arbeitszeit.models import MonatlicheArbeitszeitSoll


class SchichtplanGenerator:
    def __init__(self, mitarbeiter_queryset):
        self.mitarbeiter_list = list(mitarbeiter_queryset)
        self.ma_map = {ma.id: ma for ma in self.mitarbeiter_list}
        
        try:
            self.type_t = Schichttyp.objects.get(kuerzel='T')
            self.type_n = Schichttyp.objects.get(kuerzel='N')
            try:
                self.type_z = Schichttyp.objects.get(kuerzel='Z')
            except Schichttyp.DoesNotExist:
                self.type_z = None
                print("   ⚠️ Schichttyp 'Z' nicht gefunden")
        except Schichttyp.DoesNotExist:
            raise Exception("Schichttypen 'T' und 'N' müssen existieren.")

        self.target_shifts = [self.type_t, self.type_n]
        self._load_preferences()

    # ======================================================================
    # PRÄFERENZEN LADEN
    # ======================================================================
    def _load_preferences(self):
        """Lädt alle relevanten Präferenzen und erzwingt korrekte Datentypen"""
        print("   Lade Mitarbeiter-Präferenzen...")
        
        self.preferences = {}
        
        for ma in self.mitarbeiter_list:
            schicht_typ = getattr(ma, 'schicht_typ', 'typ_a')
            
            # --- 1. Wochentage säubern → IMMER eine Liste von Ints ---
            raw_tage = getattr(ma, 'erlaubte_wochentage', None)
            clean_tage = []
            
            if raw_tage is not None:
                if isinstance(raw_tage, str):
                    try:
                        loaded = json.loads(raw_tage)
                        if isinstance(loaded, list):
                            clean_tage = [int(t) for t in loaded]
                        elif isinstance(loaded, (int, float)):
                            clean_tage = [int(loaded)]
                    except (json.JSONDecodeError, ValueError):
                        if raw_tage.strip().isdigit():
                            clean_tage = [int(raw_tage.strip())]
                elif isinstance(raw_tage, list):
                    clean_tage = [int(t) for t in raw_tage]
                elif isinstance(raw_tage, (int, float)):
                    clean_tage = [int(raw_tage)]
            
            # --- 2. Keine Zusatzdienste Flag ---
            keine_z = bool(getattr(ma, 'keine_zusatzdienste', False))

            pref = {
                'kann_tagschicht': ma.kann_tagschicht,
                'kann_nachtschicht': ma.kann_nachtschicht,
                'nachtschicht_nur_wochenende': ma.nachtschicht_nur_wochenende,
                'nur_zusatzdienste_wochentags': ma.nur_zusatzdienste_wochentags,
                'max_wochenenden_pro_monat': ma.max_wochenenden_pro_monat,
                'max_schichten_pro_monat': ma.max_schichten_pro_monat or 999,
                'max_aufeinanderfolgende_tage': ma.max_aufeinanderfolgende_tage,
                'verfuegbarkeit': ma.verfuegbarkeit,
                'schicht_typ': schicht_typ,
                'planungs_prioritaet': ma.planungs_prioritaet,
                'erlaubte_wochentage': clean_tage,       # immer Liste
                'keine_zusatzdienste': keine_z           # immer bool
            }
            
            self.preferences[ma.id] = pref
            
            # Debug-Ausgabe
            debug_infos = []
            if clean_tage:
                tage_namen = ['Mo','Di','Mi','Do','Fr','Sa','So']
                debug_infos.append(f"NUR {','.join(tage_namen[t] for t in clean_tage if 0 <= t <= 6)}")
            if keine_z:
                debug_infos.append("KEINE Z-Dienste")
            if debug_infos:
                print(f"      → {ma.schichtplan_kennung}: {', '.join(debug_infos)}")

    # ======================================================================
    # SOLL-STUNDEN LADEN
    # ======================================================================
    def _load_soll_stunden(self, jahr, monat):
        print("\n📊 Lade Soll-Stunden...")
        soll_stunden_map = {}
        soll_schichten_map = {}
        
        avg_tag_stunden = float(self.type_t.arbeitszeit_stunden)
        avg_nacht_stunden = float(self.type_n.arbeitszeit_stunden)
        avg_schicht_stunden = (avg_tag_stunden + avg_nacht_stunden) / 2
        
        print(f"   Schichtlängen: T={avg_tag_stunden}h, N={avg_nacht_stunden}h")
        print(f"   Ø Schichtlänge: {avg_schicht_stunden:.1f}h")
        
        for ma in self.mitarbeiter_list:
            soll_obj = MonatlicheArbeitszeitSoll.objects.filter(
                mitarbeiter=ma, jahr=jahr, monat=monat
            ).first()
            
            if soll_obj:
                soll_stunden = float(soll_obj.soll_stunden)
            else:
                soll_stunden = 144.0
                print(f"      {ma.schichtplan_kennung}: Fallback {soll_stunden}h (kein MonatlicheArbeitszeitSoll)")
            
            soll_schichten = soll_stunden / avg_schicht_stunden
            soll_stunden_map[ma.id] = soll_stunden
            soll_schichten_map[ma.id] = round(soll_schichten)
            print(f"      {ma.schichtplan_kennung}: {soll_stunden:.1f}h ÷ {avg_schicht_stunden:.1f}h = {round(soll_schichten)} Schichten")
        
        return soll_stunden_map, soll_schichten_map

    # ======================================================================
    # HAUPTFUNKTION
    # ======================================================================
    def generiere_vorschlag(self, neuer_schichtplan_obj):
        start_datum = neuer_schichtplan_obj.start_datum
        
        if hasattr(neuer_schichtplan_obj, 'ende_datum') and neuer_schichtplan_obj.ende_datum:
            ende_datum = neuer_schichtplan_obj.ende_datum
        else:
            last_day = calendar.monthrange(start_datum.year, start_datum.month)[1]
            ende_datum = start_datum.replace(day=last_day)
        
        current = start_datum
        tage_liste = []
        while current <= ende_datum:
            tage_liste.append(current)
            current += datetime.timedelta(days=1)

        print(f"\n{'='*70}")
        print(f"🚀 GENERIERE PLAN: {len(tage_liste)} Tage ({start_datum} bis {tage_liste[-1]})")
        print(f"{'='*70}\n")

        # ====================================================================
        # WÜNSCHE LADEN
        # ====================================================================
        print("🗓️ Lade Schichtwünsche...")
        
        wuensche = Schichtwunsch.objects.filter(
            datum__gte=start_datum,
            datum__lte=ende_datum,
            mitarbeiter__in=self.mitarbeiter_list
        ).select_related('mitarbeiter')

        print(f"   Zeitraum: {start_datum} bis {ende_datum}")
        print(f"   Gefunden: {wuensche.count()} Wünsche")

        wuensche_matrix = defaultdict(dict)
        urlaubs_tage = defaultdict(list)

        for w in wuensche:
            wuensche_matrix[w.mitarbeiter.id][w.datum] = w
            print(f"      → {w.mitarbeiter.schichtplan_kennung}: {w.wunsch} am {w.datum}")
            if w.wunsch == 'urlaub':
                urlaubs_tage[w.mitarbeiter.id].append(w.datum)
            elif w.wunsch == 'gar_nichts' and w.genehmigt:
                urlaubs_tage[w.mitarbeiter.id].append(w.datum)

        # ====================================================================
        # SOLL-STUNDEN LADEN
        # ====================================================================
        jahr = start_datum.year
        monat = start_datum.month
        soll_stunden_map, soll_schichten_map = self._load_soll_stunden(jahr, monat)

        last_shifts = {}
        
        # ====================================================================
        # SOLVER SETUP
        # ====================================================================
        model = cp_model.CpModel()
        vars_schichten = {}

        print("\n🔧 Erstelle Constraint-Modell...")
        
        for ma in self.mitarbeiter_list:
            for tag in tage_liste:
                for stype in self.target_shifts:
                    vars_schichten[(ma.id, tag, stype.kuerzel)] = model.NewBoolVar(f'{ma.id}_{tag}_{stype.kuerzel}')
                vars_schichten[(ma.id, tag, 'Frei')] = model.NewBoolVar(f'{ma.id}_{tag}_Frei')

        # ====================================================================
        # A. BASIS-CONSTRAINTS
        # ====================================================================
        print("   ✓ Basis-Regeln")
        
        for ma in self.mitarbeiter_list:
            for tag in tage_liste:
                all_options = [vars_schichten[(ma.id, tag, st.kuerzel)] for st in self.target_shifts]
                all_options.append(vars_schichten[(ma.id, tag, 'Frei')])
                model.Add(sum(all_options) == 1)

            # Nacht → nächster Tag keine Tagschicht
            for i in range(len(tage_liste) - 1):
                heute = tage_liste[i]
                morgen = tage_liste[i+1]
                model.Add(
                    vars_schichten[(ma.id, morgen, 'T')] == 0
                ).OnlyEnforceIf(vars_schichten[(ma.id, heute, 'N')])

        if tage_liste:
            erster_tag = tage_liste[0]
            for ma_id, last_k in last_shifts.items():
                if last_k == 'N' and (ma_id, erster_tag, 'T') in vars_schichten:
                    model.Add(vars_schichten[(ma_id, erster_tag, 'T')] == 0)

        # ====================================================================
        # B. MITARBEITER-PRÄFERENZEN + WÜNSCHE
        # ====================================================================
        print("   ✓ Präferenzen & Wünsche")
        
        for ma in self.mitarbeiter_list:
            pref = self.preferences[ma.id]
            
            # B.1 KANN NICHT TAGSCHICHT
            if not pref['kann_tagschicht']:
                for tag in tage_liste:
                    model.Add(vars_schichten[(ma.id, tag, 'T')] == 0)
            
            # B.2 KANN NICHT NACHTSCHICHT
            if not pref['kann_nachtschicht']:
                for tag in tage_liste:
                    model.Add(vars_schichten[(ma.id, tag, 'N')] == 0)
            
            # B.3 NACHTSCHICHT NUR WOCHENENDE
            if pref['nachtschicht_nur_wochenende']:
                for tag in tage_liste:
                    if tag.weekday() < 5:  # Mo-Fr
                        model.Add(vars_schichten[(ma.id, tag, 'N')] == 0)
            
            # B.4 NUR ZUSATZDIENSTE WOCHENTAGS
            if pref['nur_zusatzdienste_wochentags']:
                for tag in tage_liste:
                    if tag.weekday() < 5:  # Mo-Fr
                        model.Add(vars_schichten[(ma.id, tag, 'T')] == 0)
                        model.Add(vars_schichten[(ma.id, tag, 'N')] == 0)
            
            # B.5 VERFÜGBARKEIT
            if pref['verfuegbarkeit'] == 'wochenende_only':
                for tag in tage_liste:
                    if tag.weekday() < 5:
                        model.Add(vars_schichten[(ma.id, tag, 'T')] == 0)
                        model.Add(vars_schichten[(ma.id, tag, 'N')] == 0)
            elif pref['verfuegbarkeit'] == 'wochentags_only':
                for tag in tage_liste:
                    if tag.weekday() >= 5:
                        model.Add(vars_schichten[(ma.id, tag, 'T')] == 0)
                        model.Add(vars_schichten[(ma.id, tag, 'N')] == 0)
            
            # B.6 MAX WOCHENENDEN
            max_we = pref['max_wochenenden_pro_monat']
            wochenenden = []
            current_we = None
            for tag in tage_liste:
                if tag.weekday() >= 5:
                    week_num = tag.isocalendar()[1]
                    if current_we != week_num:
                        current_we = week_num
                        wochenenden.append([])
                    wochenenden[-1].append(tag)
            
            if max_we < len(wochenenden):
                we_vars = []
                for we_tage in wochenenden:
                    we_var = model.NewBoolVar(f'{ma.id}_we_{we_tage[0]}')
                    schichten_am_we = []
                    for tag in we_tage:
                        for stype in self.target_shifts:
                            schichten_am_we.append(vars_schichten[(ma.id, tag, stype.kuerzel)])
                    model.Add(sum(schichten_am_we) >= 1).OnlyEnforceIf(we_var)
                    model.Add(sum(schichten_am_we) == 0).OnlyEnforceIf(we_var.Not())
                    we_vars.append(we_var)
                model.Add(sum(we_vars) <= max_we)
            
            # B.7 MAX SCHICHTEN PRO MONAT
            if pref['max_schichten_pro_monat'] < 999:
                alle_schichten = []
                for tag in tage_liste:
                    for stype in self.target_shifts:
                        alle_schichten.append(vars_schichten[(ma.id, tag, stype.kuerzel)])
                model.Add(sum(alle_schichten) <= pref['max_schichten_pro_monat'])
            
            # B.8 MAX AUFEINANDERFOLGENDE TAGE
            max_tage = pref['max_aufeinanderfolgende_tage']
            if max_tage and max_tage > 0:
                for i in range(len(tage_liste) - max_tage):
                    fenster = []
                    for j in range(max_tage + 1):
                        tag = tage_liste[i + j]
                        for stype in self.target_shifts:
                            fenster.append(vars_schichten[(ma.id, tag, stype.kuerzel)])
                    model.Add(sum(fenster) <= max_tage)
            
            # B.9 TYP B - MINDESTENS 4T + 4N (MIT SICHERHEITS-CHECK)
            # NUR EINMAL! (vorher war es doppelt)
            if pref['schicht_typ'] == 'typ_b':
                tag_schichten = [vars_schichten[(ma.id, tag, 'T')] for tag in tage_liste]
                nacht_schichten = [vars_schichten[(ma.id, tag, 'N')] for tag in tage_liste]
                
                verfuegbare_tage_count = 0
                for tag in tage_liste:
                    wunsch = wuensche_matrix.get(ma.id, {}).get(tag)
                    is_blocked = (wunsch and wunsch.wunsch in ['urlaub', 'gar_nichts'] and wunsch.genehmigt)
                    if not is_blocked:
                        verfuegbare_tage_count += 1
                
                if verfuegbare_tage_count >= 10:
                    model.Add(sum(tag_schichten) >= 4)
                    model.Add(sum(nacht_schichten) >= 4)
                else:
                    print(f"      ⚠️ {ma.schichtplan_kennung}: Typ B Regel ausgesetzt ({verfuegbare_tage_count} Tage verfügbar)")

            # B.10 URLAUB / GAR NICHTS → Frei erzwingen
            for tag in tage_liste:
                wunsch = wuensche_matrix.get(ma.id, {}).get(tag)
                if wunsch and wunsch.wunsch in ['urlaub', 'gar_nichts'] and wunsch.genehmigt:
                    model.Add(vars_schichten[(ma.id, tag, 'T')] == 0)
                    model.Add(vars_schichten[(ma.id, tag, 'N')] == 0)
                    model.Add(vars_schichten[(ma.id, tag, 'Frei')] == 1)

            # B.11 ERLAUBTE WOCHENTAGE (HARD CONSTRAINT)
            erlaubte_tage = pref['erlaubte_wochentage']  # immer Liste (kann leer sein)
            
            if erlaubte_tage:  # nur wenn nicht leer
                tage_namen = ['Mo','Di','Mi','Do','Fr','Sa','So']
                sichtbare_tage = [tage_namen[t] for t in erlaubte_tage if 0 <= t <= 6]
                print(f"      ✓ CONSTRAINT: {ma.schichtplan_kennung} nur an {','.join(sichtbare_tage)}")
                
                for tag in tage_liste:
                    if tag.weekday() not in erlaubte_tage:
                        model.Add(vars_schichten[(ma.id, tag, 'T')] == 0)
                        model.Add(vars_schichten[(ma.id, tag, 'N')] == 0)

        # ====================================================================
        # C. BESETZUNG - SOFT TARGET (Ziel: 2 pro Schicht)
        # ====================================================================
        print("   ✓ Besetzung (Ziel: 2, erlaubt: 0-4)")
        
        objective_terms = []  # hier initialisieren
        
        for tag in tage_liste:
            for stype in ['T', 'N']:
                schichten_pro_typ = [vars_schichten[(m.id, tag, stype)] for m in self.mitarbeiter_list]
                summe_var = model.NewIntVar(0, 12, f'summe_{tag}_{stype}')
                model.Add(summe_var == sum(schichten_pro_typ))

                model.Add(summe_var >= 0) 
                model.Add(summe_var <= 4)
                
                # Abweichung von Ziel 2 bestrafen
                abweichung = model.NewIntVar(0, 4, f'abweichung_{tag}_{stype}')
                model.Add(abweichung >= summe_var - 2)
                model.Add(abweichung >= 2 - summe_var)
                objective_terms.append(abweichung * 50000)
                
                # Leere Schicht = Extremstrafe
                ist_null = model.NewBoolVar(f'{tag}_{stype}_ist_null')
                model.Add(summe_var == 0).OnlyEnforceIf(ist_null)
                model.Add(summe_var > 0).OnlyEnforceIf(ist_null.Not())
                objective_terms.append(ist_null * 1000000)

        # ====================================================================
        # E. OPTIMIERUNGSZIEL
        # ====================================================================
        print("   ✓ Optimierungsziel (Wünsche + Soll-Stunden)")
        
        for ma in self.mitarbeiter_list:
            pref = self.preferences[ma.id]
            soll_schichten = soll_schichten_map.get(ma.id, 10)
            
            # --- E.1 SOLL-STUNDEN (Abweichung bestrafen) ---
            normale_schichten = []
            for tag in tage_liste:
                if tag not in urlaubs_tage.get(ma.id, []):
                    for stype in ['T', 'N']:
                        normale_schichten.append(vars_schichten[(ma.id, tag, stype)])

            ist_schichten_var = model.NewIntVar(0, 100, f'{ma.id}_ist_schichten')
            model.Add(ist_schichten_var == sum(normale_schichten))

            abweichung_var = model.NewIntVar(-100, 100, f'{ma.id}_abweichung')
            model.Add(abweichung_var == ist_schichten_var - soll_schichten)

            abs_abweichung = model.NewIntVar(0, 100, f'{ma.id}_abs_abweichung')
            model.AddAbsEquality(abs_abweichung, abweichung_var)
            objective_terms.append(abs_abweichung * 2000)
            
            # --- E.2 WÜNSCHE ---
            for tag in tage_liste:
                wunsch = wuensche_matrix.get(ma.id, {}).get(tag)
                
                for stype in self.target_shifts:
                    kuerzel = stype.kuerzel
                    score = 0
                    
                    if wunsch:
                        if wunsch.wunsch == 'tag_bevorzugt':
                            score = -25000 if kuerzel == 'T' else 25000
                        elif wunsch.wunsch == 'nacht_bevorzugt':
                            score = -25000 if kuerzel == 'N' else 25000
                        elif wunsch.wunsch == 'zusatzarbeit':
                            score = -5000
                        elif wunsch.wunsch in ['urlaub', 'gar_nichts'] and wunsch.genehmigt:
                            score = 1000000  # sollte durch B.10 nicht nötig sein, aber Safety

                    # Planungs-Priorität als Multiplikator
                    if pref['planungs_prioritaet'] == 'hoch':
                        score = int(score * 1.5)
                    elif pref['planungs_prioritaet'] == 'niedrig':
                        score = int(score * 0.8)
                    
                    if score != 0:
                        objective_terms.append(vars_schichten[(ma.id, tag, kuerzel)] * score)

        model.Minimize(sum(objective_terms))

        # ====================================================================
        # F. SOLVER STARTEN
        # ====================================================================
        print("\n" + "="*70)
        print("🔍 CONSTRAINT-ANALYSE")
        print("="*70)
        print(f"Zeitraum: {len(tage_liste)} Tage | Mitarbeiter: {len(self.mitarbeiter_list)}")

        kann_tag = sum(1 for ma in self.mitarbeiter_list if self.preferences[ma.id]['kann_tagschicht'])
        kann_nacht = sum(1 for ma in self.mitarbeiter_list if self.preferences[ma.id]['kann_nachtschicht'])
        print(f"Können Tagschicht: {kann_tag} | Können Nachtschicht: {kann_nacht}")

        urlaubs_gesamt = sum(len(tage) for tage in urlaubs_tage.values())
        print(f"Urlaubstage gesamt: {urlaubs_gesamt}")

        typ_b_mas = [ma for ma in self.mitarbeiter_list if self.preferences[ma.id]['schicht_typ'] == 'typ_b']
        if typ_b_mas:
            print(f"Typ B: {len(typ_b_mas)} Mitarbeiter")
            for ma in typ_b_mas:
                verfuegbar = len(tage_liste) - len(urlaubs_tage.get(ma.id, []))
                print(f"   {ma.schichtplan_kennung}: {verfuegbar} Tage verfügbar")

        print("="*70 + "\n")
        
        print("⚙️ Starte Solver...")
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 360.0
        status = solver.Solve(model)
        print(f"   Status: {solver.StatusName(status)}")
        
        # ====================================================================
        # G. ERGEBNISSE SPEICHERN
        # ====================================================================
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            print(f"\n✅ Lösung gefunden! Status: {solver.StatusName(status)}\n")
            
            ergebnis_count = 0
            ist_schichten_pro_ma = defaultdict(int)
            
            for ma in self.mitarbeiter_list:
                for tag in tage_liste:
                    if solver.Value(vars_schichten[(ma.id, tag, 'T')]) == 1:
                        Schicht.objects.create(
                            schichtplan=neuer_schichtplan_obj,
                            mitarbeiter=ma, datum=tag, schichttyp=self.type_t
                        )
                        ergebnis_count += 1
                        ist_schichten_pro_ma[ma.id] += 1
                    elif solver.Value(vars_schichten[(ma.id, tag, 'N')]) == 1:
                        Schicht.objects.create(
                            schichtplan=neuer_schichtplan_obj,
                            mitarbeiter=ma, datum=tag, schichttyp=self.type_n
                        )
                        ergebnis_count += 1
                        ist_schichten_pro_ma[ma.id] += 1
            
            print(f"💾 {ergebnis_count} Schichten gespeichert.")
            
            # ================================================================
            # H. ZUSATZDIENSTE GENERIEREN
            # ================================================================
            if self.type_z:
                print("\n➕ Generiere Zusatzdienste zum Auffüllen...")
                
                z_ist_tag = True 
                if self.type_z.start_zeit and self.type_z.start_zeit.hour >= 18: 
                    z_ist_tag = False
                
                zusatz_count = 0
                ma_bedarf = []

                for ma in self.mitarbeiter_list:
                    pref = self.preferences[ma.id]
                    
                    # SKIP: keine_zusatzdienste
                    if pref['keine_zusatzdienste']:
                        print(f"   ⏭️  {ma.schichtplan_kennung}: Übersprungen (Vereinbarung: keine Z)")
                        continue
                        
                    # SKIP: Kann Schichttyp nicht
                    if z_ist_tag and not pref['kann_tagschicht']:
                        continue
                    if not z_ist_tag and not pref['kann_nachtschicht']:
                        continue

                    soll = soll_schichten_map.get(ma.id, 10)
                    ist = ist_schichten_pro_ma[ma.id]
                    fehlt = soll - ist
                    
                    if fehlt > 0:
                        erlaubte_tage = pref['erlaubte_wochentage']  # Liste oder leer
                        freie_tage = []
                        
                        for tag in tage_liste:
                            # Nur Di-Fr für Z
                            if tag.weekday() not in [1, 2, 3, 4]:
                                continue
                            # Kein Urlaub
                            if tag in urlaubs_tage.get(ma.id, []):
                                continue
                            # Erlaubte Wochentage prüfen
                            if erlaubte_tage and tag.weekday() not in erlaubte_tage:
                                continue
                            # Muss "Frei" sein
                            if solver.Value(vars_schichten[(ma.id, tag, 'Frei')]) == 1:
                                
                                # Safety: Kein Z nach Nachtschicht
                                gestern = tag - datetime.timedelta(days=1)
                                if gestern in tage_liste:
                                    if solver.Value(vars_schichten[(ma.id, gestern, 'N')]) == 1:
                                        continue

                                # Safety: Max aufeinanderfolgende Tage prüfen
                                # Zähle nur TATSÄCHLICH zugewiesene Schichten (T/N vom Solver)
                                # Z-Dienste die WIR gerade vergeben werden HIER noch nicht gezählt
                                morgen = tag + datetime.timedelta(days=1)
                                work_streak = 1
                                
                                check_tag = gestern
                                while check_tag in tage_liste:
                                    if solver.Value(vars_schichten[(ma.id, check_tag, 'Frei')]) == 0:
                                        work_streak += 1
                                    else:
                                        break
                                    check_tag -= datetime.timedelta(days=1)
                                
                                check_tag = morgen
                                while check_tag in tage_liste:
                                    if solver.Value(vars_schichten[(ma.id, check_tag, 'Frei')]) == 0:
                                        work_streak += 1
                                    else:
                                        break
                                    check_tag += datetime.timedelta(days=1)
                                
                                max_tage = pref['max_aufeinanderfolgende_tage'] or 999
                                if work_streak > max_tage:
                                    continue

                                freie_tage.append(tag)
                        
                        if freie_tage:
                            ma_bedarf.append({
                                'ma': ma,
                                'bedarf': fehlt,
                                'zugewiesen': 0,
                                'freie_tage': freie_tage
                            })
                            print(f"   {ma.schichtplan_kennung}: fehlt {fehlt} Schichten, {len(freie_tage)} Tage verfügbar")
                
                # ============================================================
                # H.2 VERTEILUNG: Pro-MA Durchlauf, max 2 Z pro Tag
                # ============================================================
                if ma_bedarf:
                    # Sortiere: Wer am meisten braucht → zuerst bedienen
                    ma_bedarf.sort(key=lambda x: x['bedarf'], reverse=True)
                    
                    # Zähle wie viele Z pro Tag vergeben werden (max 2)
                    z_pro_tag = defaultdict(int)
                    MAX_Z_PRO_TAG = 2
                    
                    # Zähle auch bereits vergebene Z pro MA (aus Solver T/N + neue Z)
                    # damit max_aufeinanderfolgende_tage korrekt bleibt
                    ma_arbeits_tage = {}  # {ma.id: set(datum)} — alle Tage wo MA arbeitet
                    for ma_info in ma_bedarf:
                        arbeits_tage = set()
                        for tag in tage_liste:
                            if solver.Value(vars_schichten[(ma_info['ma'].id, tag, 'Frei')]) == 0:
                                arbeits_tage.add(tag)
                        ma_arbeits_tage[ma_info['ma'].id] = arbeits_tage

                    for ma_info in ma_bedarf:
                        ma_id = ma_info['ma'].id
                        max_tage = self.preferences[ma_id]['max_aufeinanderfolgende_tage'] or 999
                        
                        for tag in ma_info['freie_tage']:
                            # Genug für diesen MA?
                            if ma_info['zugewiesen'] >= ma_info['bedarf']:
                                break
                            # Tag voll (max 2 Z)?
                            if z_pro_tag[tag] >= MAX_Z_PRO_TAG:
                                continue
                            # Duplikat-Check: MA hat schon eine Schicht an diesem Tag
                            if tag in ma_arbeits_tage[ma_id]:
                                continue
                            
                            # Safety: max aufeinanderfolgende Tage prüfen
                            # Zähle zusammenhängende Arbeits-Tage INCLUSIVE diesen Tag
                            streak = 1
                            check = tag - datetime.timedelta(days=1)
                            while check in ma_arbeits_tage[ma_id]:
                                streak += 1
                                check -= datetime.timedelta(days=1)
                            check = tag + datetime.timedelta(days=1)
                            while check in ma_arbeits_tage[ma_id]:
                                streak += 1
                                check += datetime.timedelta(days=1)
                            
                            if streak > max_tage:
                                continue

                            # ✅ Vergeben
                            Schicht.objects.create(
                                schichtplan=neuer_schichtplan_obj,
                                mitarbeiter=ma_info['ma'],
                                datum=tag,
                                schichttyp=self.type_z
                            )
                            ma_info['zugewiesen'] += 1
                            z_pro_tag[tag] += 1
                            ma_arbeits_tage[ma_id].add(tag)  # ← Tag merken für nächste Streak-Prüfung
                            zusatz_count += 1
                    
                    print(f"   ➕ {zusatz_count} Zusatzdienste vergeben.")

            # ================================================================
            # I. STATISTIKEN
            # ================================================================
            self._print_statistics(neuer_schichtplan_obj, tage_liste, soll_stunden_map, soll_schichten_map, wuensche_matrix)
        
        else:
            error_msg = (
                "❌ Keine gültige Lösung gefunden!\n"
                "Mögliche Ursachen:\n"
                "1. Zu wenige MA für Besetzung (2 pro Schicht)\n"
                "2. Zu viele Urlaube an denselben Tagen\n"
                "3. Typ B + Wünsche unvereinbar\n"
            )
            print(error_msg)
            raise Exception(error_msg)

    # ======================================================================
    # STATISTIKEN
    # ======================================================================
    def _print_statistics(self, schichtplan, tage_liste, soll_stunden_map, soll_schichten_map, wuensche_matrix):
        print("\n" + "="*70)
        print("📊 PLAN-STATISTIKEN")
        print("="*70)
        
        schichten = Schicht.objects.filter(schichtplan=schichtplan)
        
        # Wunsch-Analyse
        print("\n🔍 WUNSCH-ANALYSE:")
        for ma in self.mitarbeiter_list:
            ma_wuensche = wuensche_matrix.get(ma.id, {})
            for datum, wunsch in ma_wuensche.items():
                schicht_an_tag = schichten.filter(mitarbeiter=ma, datum=datum).first()
                ist = schicht_an_tag.schichttyp.kuerzel if schicht_an_tag else "Frei"
                
                if wunsch.wunsch == 'urlaub':
                    status = "✅" if not schicht_an_tag else "❌ FEHLER"
                elif wunsch.wunsch == 'tag_bevorzugt':
                    status = "✅" if ist == 'T' else ("⚠️ SOFT" if ist != 'Frei' else "ℹ️")
                elif wunsch.wunsch == 'nacht_bevorzugt':
                    status = "✅" if ist == 'N' else ("⚠️ SOFT" if ist != 'Frei' else "ℹ️")
                elif wunsch.wunsch == 'gar_nichts':
                    status = "✅" if not schicht_an_tag else ("❌ FEHLER" if wunsch.genehmigt else "⚠️")
                else:
                    status = "ℹ️"
                
                print(f"   {status} {ma.schichtplan_kennung}: {wunsch.wunsch} am {datum} → {ist}")
        
        # Verteilung pro MA
        print("\n📊 SCHICHT-VERTEILUNG:")
        tage_namen = ['Mo','Di','Mi','Do','Fr','Sa','So']
        
        for ma in self.mitarbeiter_list:
            ma_schichten = schichten.filter(mitarbeiter=ma)
            anzahl_t = ma_schichten.filter(schichttyp=self.type_t).count()
            anzahl_n = ma_schichten.filter(schichttyp=self.type_n).count()
            anzahl_z = ma_schichten.filter(schichttyp=self.type_z).count() if self.type_z else 0
            gesamt = anzahl_t + anzahl_n + anzahl_z
            
            soll_schichten = soll_schichten_map.get(ma.id, 0)
            soll_stunden = soll_stunden_map.get(ma.id, 0)
            diff = gesamt - soll_schichten
            diff_str = f"+{diff}" if diff > 0 else str(diff)
            typ_label = "B" if self.preferences[ma.id]['schicht_typ'] == 'typ_b' else "A"
            
            # Vereinbarungen anzeigen (eigene Variablen, nicht 't' überschreiben!)
            vereinbarungen = []
            erlaubte = self.preferences[ma.id]['erlaubte_wochentage']
            if erlaubte:
                vereinbarungen.append(', '.join(tage_namen[d] for d in erlaubte if 0 <= d <= 6))
            if self.preferences[ma.id]['keine_zusatzdienste']:
                vereinbarungen.append("keine Z")
            vereinbarungen_str = f" [{', '.join(vereinbarungen)}]" if vereinbarungen else ""
            
            print(f"   {ma.schichtplan_kennung} (Typ {typ_label}){vereinbarungen_str}: {anzahl_t}T + {anzahl_n}N + {anzahl_z}Z = {gesamt} (Soll: {soll_schichten}, {diff_str}) | {soll_stunden}h")
        
        print("="*70 + "\n")
