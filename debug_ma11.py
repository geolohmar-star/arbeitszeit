import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
django.setup()

import datetime
from arbeitszeit.models import Mitarbeiter, MonatlicheArbeitszeitSoll
from schichtplan.models import Schichtplan, Schicht

ma = Mitarbeiter.objects.get(schichtplan_kennung='MA11')
print(f"=== MA11: {ma.vollname} ===\n")

# 1. PRÄFERENZEN
print("📋 PRÄFERENZEN:")
print(f"   kann_tagschicht:              {ma.kann_tagschicht}")
print(f"   kann_nachtschicht:            {ma.kann_nachtschicht}")
print(f"   nachtschicht_nur_wochenende:  {ma.nachtschicht_nur_wochenende}")
print(f"   nur_zusatzdienste_wochentags: {ma.nur_zusatzdienste_wochentags}")
print(f"   nur_zusatzarbeiten:           {ma.nur_zusatzarbeiten}")
print(f"   verfuegbarkeit:               {ma.verfuegbarkeit}")
print(f"   schicht_typ:                  {ma.schicht_typ}")
print(f"   max_wochenenden_pro_monat:    {ma.max_wochenenden_pro_monat}")
print(f"   max_schichten_pro_monat:      {ma.max_schichten_pro_monat}")
print(f"   max_aufeinanderfolgende_tage: {ma.max_aufeinanderfolgende_tage}")
print(f"   planungs_prioritaet:          {ma.planungs_prioritaet}")
print(f"   erlaubte_wochentage:          {ma.erlaubte_wochentage}")
print(f"   keine_zusatzdienste:          {ma.keine_zusatzdienste}")

# 2. VEREINBARUNG
print("\n📄 VEREINBARUNGEN:")
for v in ma.arbeitszeitvereinbarungen.all().order_by('-gueltig_ab'):
    print(f"   Status: {v.status} | Wochenstunden: {v.wochenstunden}h | ab {v.gueltig_ab} bis {v.gueltig_bis}")

# 3. SOLL-STUNDEN
print("\n📊 MonatlicheArbeitszeitSoll:")
for s in MonatlicheArbeitszeitSoll.objects.filter(mitarbeiter=ma, jahr=2026).order_by('monat'):
    print(f"   2026-{s.monat:02d}: {s.soll_stunden}h (Wochenstunden: {s.wochenstunden}h)")

# 4. SCHICHTEN aus dem aktuellen Plan (APR)
print("\n🗓️  SCHICHTEN im aktuellen Plan:")
plan = Schichtplan.objects.order_by('-erstellt_am').first()
print(f"   Plan: {plan.name} ({plan.start_datum} bis {plan.ende_datum})\n")

schichten = Schicht.objects.filter(
    schichtplan=plan,
    mitarbeiter=ma
).order_by('datum')

t_count = 0
n_count = 0
z_count = 0

for s in schichten:
    tag_name = s.datum.strftime('%A')
    print(f"   {s.datum} ({tag_name:>12}): {s.schichttyp.kuerzel}")
    if s.schichttyp.kuerzel == 'T': t_count += 1
    elif s.schichttyp.kuerzel == 'N': n_count += 1
    elif s.schichttyp.kuerzel == 'Z': z_count += 1

print(f"\n   Summe: {t_count}T + {n_count}N + {z_count}Z = {t_count+n_count+z_count}")

# 5. WÜNSCHE für MA11
print("\n🗳️  WÜNSCHE (April 2026):")
from schichtplan.models import Schichtwunsch
wuensche = Schichtwunsch.objects.filter(
    mitarbeiter=ma,
    datum__year=2026,
    datum__month=4
).order_by('datum')

if wuensche.exists():
    for w in wuensche:
        print(f"   {w.datum}: {w.wunsch} (genehmigt: {w.genehmigt})")
else:
    print("   Keine Wünsche eingegeben.")
