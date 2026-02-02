# schichtplan/views.py - ANGEPASST für MA1-MA15 mit Präferenzen
"""
Views für das Schichtplan-Modul
ANGEPASST: Filtert nur Mitarbeiter mit Kennung MA1-MA15

"""
from django.db.models.functions import Length  # ← Für Sortierung
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count
from django.http import JsonResponse
from django.views.generic.edit import CreateView
from django.urls import reverse_lazy
from django.db import transaction
from django import forms
from collections import defaultdict

from datetime import timedelta
from calendar import day_name
import tempfile

# Models
from arbeitszeit.models import Mitarbeiter
from .models import Schichtplan, Schicht, Schichttyp, SchichtwunschPeriode, Schichtwunsch  # ← Schichtwunsch hinzufügen!


# Forms
from .forms import ExcelImportForm, SchichtplanForm, SchichtForm

# Services
from .services import SchichtplanGenerator

# Utils
try:
    from .utils.excel_import import SchichtplanImporter
except ImportError:
    try:
        from .utils.xls_importer import SchichtplanImporter
    except ImportError:
        SchichtplanImporter = None

#Wunschplan
from datetime import datetime, timedelta
from calendar import monthrange





# ============================================================================
# HELPER FUNKTIONEN
# ============================================================================
def ist_schichtplaner(user):
    # Wenn du als Admin eingeloggt bist, darfst du immer alles
    if user.is_superuser or user.is_staff:
        return True
    
    # Ansonsten prüfe die Rolle im Mitarbeiter-Profil
    if hasattr(user, 'mitarbeiter'):
        return user.mitarbeiter.rolle == 'schichtplaner'
    
    return False

def ist_schichtplaner(user):
    """Prüft, ob der User Schichtplaner-Rechte hat"""
    if user.is_staff or user.is_superuser:
        return True
    
    if hasattr(user, 'mitarbeiter'):
        return user.mitarbeiter.rolle == 'schichtplaner'
    
    return False


def get_planbare_mitarbeiter():
    """
    Gibt nur Mitarbeiter zurück, die für Schichtplanung relevant sind.
    
    Kriterien:
    - Aktiv = True
    - Kennung = MA1 bis MA15
    - Verfügbarkeit != 'dauerkrank'
    """
    gueltige_kennungen = [f'MA{i}' for i in range(1, 16)]  # MA1 bis MA15
    
    return Mitarbeiter.objects.filter(
        aktiv=True,
        schichtplan_kennung__in=gueltige_kennungen
    ).exclude(
        verfuegbarkeit='dauerkrank'
    ).select_related('user')

class WunschPeriodeCreateView(CreateView):
    model = SchichtwunschPeriode
    template_name = 'schichtplan/periode_form.html'
    fields = ['name', 'fuer_monat', 'eingabe_start', 'eingabe_ende', 'status']
    success_url = reverse_lazy('schichtplan:wunsch_perioden_liste')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        
        # 1. Datumsauswahl (Nur Tag/Monat/Jahr)
        form.fields['fuer_monat'].widget = forms.DateInput(
            attrs={'type': 'date', 'class': 'form-control'}
        )
        
        # 2. Datum mit Uhrzeit (Für den Eingabezeitraum)
        form.fields['eingabe_start'].widget = forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'}
        )
        form.fields['eingabe_ende'].widget = forms.DateTimeInput(
            attrs={'type': 'datetime-local', 'class': 'form-control'}
        )
        
        # Styling für die anderen Felder
        form.fields['name'].widget.attrs.update({'class': 'form-control'})
        form.fields['status'].widget.attrs.update({'class': 'form-control'})
        
        return form

    def form_valid(self, form):
        form.instance.erstellt_von = self.request.user
        return super().form_valid(form)


# ============================================================================
# CLASS-BASED VIEW: Schichtplan erstellen
# ============================================================================

class SchichtplanCreateView(CreateView):
    """
    Erstellt einen neuen Schichtplan.
    Verwendet nur Mitarbeiter mit Kennung MA1-MA15.
    """
    
    model = Schichtplan
    form_class = SchichtplanForm
    template_name = 'schichtplan/schichtplan_erstellen.html'
    success_url = reverse_lazy('schichtplan:dashboard')

    def dispatch(self, request, *args, **kwargs):
        """Berechtigungsprüfung"""
        if not ist_schichtplaner(request.user):
            messages.error(request, "❌ Keine Berechtigung für diese Aktion.")
            return redirect('arbeitszeit:dashboard')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Speichern + Optional KI-Generierung"""
        
        ki_aktiviert = form.cleaned_data.get('vorschlag_generieren', False)
        
        try:
            with transaction.atomic():
                # 1. Schichtplan speichern
                self.object = form.save(commit=False)
                
                if hasattr(self.object, 'erstellt_von'):
                    self.object.erstellt_von = self.request.user
                
                self.object.save()
                
                print(f"✅ Schichtplan '{self.object.name}' (ID={self.object.pk}) gespeichert")
                
                # 2. KI-Generierung (falls aktiviert)
                if ki_aktiviert:
                    self._generate_with_ai()
                else:
                    messages.success(
                        self.request,
                        f"✅ Plan '{self.object.name}' wurde leer angelegt."
                    )
            
            return redirect(self.get_success_url())
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            
            messages.error(
                self.request,
                f"❌ Fehler beim Erstellen des Plans: {str(e)}"
            )
            return self.form_invalid(form)

    def _generate_with_ai(self):
        """
        KI-Generierung mit gefilterter Mitarbeiter-Liste (MA1-MA15).
        Berücksichtigt alle Präferenzen und eingereichten Schichtwünsche.
        """
        print(f"🤖 KI-Generierung für Plan '{self.object.name}' (ID={self.object.pk}) gestartet...")

        # 1. BASIS-CHECK: Mitarbeiter vorhanden?
        planbare_mitarbeiter = get_planbare_mitarbeiter()
        
        if not planbare_mitarbeiter.exists():
            messages.warning(
                self.request,
                "⚠️ Keine planbaren Mitarbeiter gefunden (MA1-MA15 aktiv/nicht dauerkrank)."
            )
            return

        # 2. BASIS-CHECK: Schichttypen vorhanden?
        required_types = ['T', 'N']
        existing_types = list(Schichttyp.objects.filter(kuerzel__in=required_types).values_list('kuerzel', flat=True))
        
        if len(existing_types) != len(required_types):
            missing = set(required_types) - set(existing_types)
            raise Exception(f"Schichttypen fehlen: {', '.join(missing)}. Bitte im Admin anlegen.")

        # 3. DATEN SAMMELN: Wünsche aus der Periode laden (falls verknüpft)
        wuensche_liste = []
        if self.object.wunschperiode:
            wuensche_liste = Schichtwunsch.objects.filter(
                periode=self.object.wunschperiode,
                mitarbeiter__in=planbare_mitarbeiter
            ).select_related('mitarbeiter')
            print(f"   ✓ {wuensche_liste.count()} Wünsche aus Periode '{self.object.wunschperiode.name}' geladen.")
        else:
            print("   ℹ️ Keine Wunschperiode verknüpft. Generierung erfolgt nur nach Stammdaten-Präferenzen.")

        # 4. GENERATOR STARTEN (Genau ein Aufruf)
        try:
            # Wir übergeben dem Generator die Mitarbeiter UND die (optionale) Wunschliste
            generator = SchichtplanGenerator(
                mitarbeiter_liste=planbare_mitarbeiter, 
                wuensche=wuensche_liste
            )
            
            generator.generiere_vorschlag(self.object)
            
            schichten_anzahl = self.object.schichten.count()
            
            messages.success(
                self.request,
                f"✅ Plan '{self.object.name}' wurde erfolgreich erstellt! "
                f"🚀 {schichten_anzahl} Schichten für {planbare_mitarbeiter.count()} "
                f"Mitarbeiter automatisch generiert."
            )
            print(f"✅ Erfolg: {schichten_anzahl} Schichten generiert.")

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise Exception(f"Die KI-Generierung schlug fehl: {str(e)}")


# ============================================================================
# REST DER VIEWS (unverändert)
# ============================================================================

@login_required
def excel_import_view(request, pk):
    """Importiert Excel-Datei in einen bestehenden Schichtplan"""
    schichtplan = get_object_or_404(Schichtplan, pk=pk)

    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung.")
        return redirect('schichtplan:dashboard')

    if request.method == 'POST':
        form = ExcelImportForm(request.POST, request.FILES)

        if form.is_valid():
            excel_file = request.FILES['excel_file']

            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                for chunk in excel_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            try:
                if SchichtplanImporter is None:
                    raise Exception("Excel-Importer nicht verfügbar!")
                
                importer = SchichtplanImporter()
                importer.import_excel_mit_zuordnung(tmp_path, schichtplan)

                messages.success(request, "✅ Excel-Datei erfolgreich importiert!")
                return redirect('schichtplan:detail', pk=schichtplan.pk)

            except Exception as e:
                messages.error(request, f"❌ Fehler beim Import: {str(e)}")

    else:
        form = ExcelImportForm()

    return render(request, 'schichtplan/excel_import.html', {
        'form': form,
        'schichtplan': schichtplan
    })


@login_required
def excel_analyse_view(request):
    """Analysiert Excel-Datei vor dem Import"""
    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')
    
    if request.method == 'POST':
        form = ExcelImportForm(request.POST, request.FILES)
        
        if form.is_valid():
            stats = {
                'info': 'Analyse-Funktion noch nicht implementiert'
            }
            
            return render(request, 'schichtplan/excel_analyse.html', {
                'stats': stats,
                'form': form,
            })
    else:
        form = ExcelImportForm()
    
    return render(request, 'schichtplan/excel_analyse.html', {
        'form': form,
    })


@login_required
def planer_dashboard(request):
    """Dashboard für Schichtplaner"""
    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung für diese Seite.")
        return redirect('arbeitszeit:dashboard')
    
    schichtplaene = Schichtplan.objects.all().order_by('-start_datum')
    
    aktive_plaene = schichtplaene.filter(status='veroeffentlicht').count()
    entwuerfe = schichtplaene.filter(status='entwurf').count()
    
    # Zeige nur planbare Mitarbeiter in den Statistiken
    planbare_ma = get_planbare_mitarbeiter()
    
    context = {
        'schichtplaene': schichtplaene,
        'aktive_plaene': aktive_plaene,
        'entwuerfe': entwuerfe,
        'mitarbeiter_gesamt': planbare_ma.count(),
        'mitarbeiter_zugeordnet': planbare_ma.exclude(schichtplan_kennung='').count(),
    }
    
    return render(request, 'schichtplan/planer_dashboard.html', context)


@login_required
def mitarbeiter_uebersicht(request):
    """Mitarbeiter-Übersicht für Schichtplaner"""
    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')
    
    # Zeige nur planbare Mitarbeiter
    mitarbeiter = get_planbare_mitarbeiter()
    
    stats = {
        'gesamt': mitarbeiter.count(),
        'zugeordnet': mitarbeiter.exclude(schichtplan_kennung='').count(),
        'nicht_zugeordnet': mitarbeiter.filter(schichtplan_kennung='').count(),
        'dauerkrank': Mitarbeiter.objects.filter(
            aktiv=True,
            verfuegbarkeit='dauerkrank'
        ).count(),
    }
    
    context = {
        'mitarbeiter': mitarbeiter,
        'mitarbeiter_liste': mitarbeiter,
        'stats': stats,
        'anzahl_siegburg': mitarbeiter.filter(standort='siegburg').count(),
        'anzahl_bonn': mitarbeiter.filter(standort='bonn').count(),
    }
    
    return render(request, 'arbeitszeit/mitarbeiter_uebersicht.html', context)


@login_required
def schichtplan_detail(request, pk):
    """Detail-Ansicht eines Schichtplans"""
    schichtplan = get_object_or_404(Schichtplan, pk=pk)

    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')

    # Alle Schichten des Plans
    schichten = schichtplan.schichten.select_related(
        'mitarbeiter', 'schichttyp'
    ).order_by('datum', 'schichttyp__start_zeit')

    # Mitarbeiter-Zuordnung (Mapping von schichtplan_kennung zu vollname)
    mitarbeiter_mapping = {ma.schichtplan_kennung: ma.vollname for ma in Mitarbeiter.objects.all()}

    kalender_daten = {}
    current_date = schichtplan.start_datum

    # Bereite die Kalender-Daten vor
    while current_date <= schichtplan.ende_datum:
        tag_schichten = schichten.filter(datum=current_date)
        kalender_daten[current_date] = {
            'datum': current_date,
            'wochentag': day_name[current_date.weekday()],
            'schichten': tag_schichten,
            'ist_wochenende': current_date.weekday() >= 5,
        }
        current_date += timedelta(days=1)

    # Mitarbeiter-Statistik
    mitarbeiter_stats = Mitarbeiter.objects.filter(
        schichten__schichtplan=schichtplan
    ).annotate(
        anzahl_schichten=Count('schichten')
    ).order_by('-anzahl_schichten')

    # Übergib das Mapping zu den Mitarbeiternamen an das Template
    context = {
        'schichtplan': schichtplan,
        'kalender_daten': kalender_daten,
        'mitarbeiter_stats': mitarbeiter_stats,
        'schichttypen': Schichttyp.objects.filter(aktiv=True),
        'mitarbeiter_mapping': mitarbeiter_mapping,  # Das Mapping hier hinzufügen
    }

    return render(request, 'schichtplan/schichtplan_detail.html', context)



@login_required
def schicht_zuweisen(request, schichtplan_pk):
    """Schicht manuell zuweisen"""
    schichtplan = get_object_or_404(Schichtplan, pk=schichtplan_pk)
    
    if not ist_schichtplaner(request.user):
        return JsonResponse({'error': 'Keine Berechtigung'}, status=403)
    
    if request.method == 'POST':
        form = SchichtForm(request.POST)
        
        if form.is_valid():
            schicht = form.save(commit=False)
            schicht.schichtplan = schichtplan
            
            try:
                schicht.save()
                messages.success(request, "✅ Schicht erfolgreich zugewiesen!")
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'schicht_id': schicht.pk,
                    })
                
                return redirect('schichtplan:detail', pk=schichtplan.pk)
                
            except Exception as e:
                messages.error(request, f"❌ Fehler beim Speichern: {e}")
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({'error': str(e)}, status=400)
        
        else:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': form.errors}, status=400)
    
    else:
        form = SchichtForm()
    
    context = {
        'schichtplan': schichtplan,
        'form': form,
    }
    
    return render(request, 'schichtplan/schicht_zuweisen.html', context)


@login_required
def schicht_loeschen(request, pk):
    """Schicht löschen"""
    schicht = get_object_or_404(Schicht, pk=pk)
    
    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung.")
        return redirect('schichtplan:dashboard')
    
    schichtplan_pk = schicht.schichtplan.pk
    
    if request.method == 'POST':
        schicht.delete()
        messages.success(request, "✅ Schicht wurde gelöscht.")
        return redirect('schichtplan:detail', pk=schichtplan_pk)
    
    context = {
        'schicht': schicht,
    }
    
    return render(request, 'schichtplan/schicht_loeschen_confirm.html', context)


@login_required
def wuensche_genehmigen(request, periode_id):
    """Schichtplaner genehmigt Wünsche"""
    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung.")
        return redirect('schichtplan:dashboard')
    
    periode = get_object_or_404(SchichtwunschPeriode, pk=periode_id)
    
    context = {
        'periode': periode,
    }
    
    return render(request, 'schichtplan/wuensche_genehmigen.html', context)

@login_required
def wunsch_perioden_liste(request):
    """Liste aller Wunschperioden für Mitarbeiter"""
    if not hasattr(request.user, 'mitarbeiter'):
        messages.error(request, "❌ Kein Mitarbeiter-Profil gefunden.")
        return redirect('arbeitszeit:dashboard')
    
    mitarbeiter = request.user.mitarbeiter
    gueltige_kennungen = [f'MA{i}' for i in range(1, 16)]
    
    # Debug
    print(f"User: {request.user.username}, Kennung: {mitarbeiter.schichtplan_kennung}")
    
    if not (ist_schichtplaner(request.user) or mitarbeiter.schichtplan_kennung in gueltige_kennungen):
        messages.error(
            request, 
            f"❌ Nur MA1-MA15 können Wünsche eintragen. Ihre Kennung: {mitarbeiter.schichtplan_kennung}"
        )
        return redirect('arbeitszeit:dashboard')
    
    # Alle Perioden laden
    perioden = SchichtwunschPeriode.objects.all().order_by('-fuer_monat')
    
    # Für jede Periode: Eigene Wünsche zählen
    for periode in perioden:
        periode.eigene_wuensche_count = periode.schichtwunsch_set.filter(
            mitarbeiter=mitarbeiter
        ).count()
    
    context = {
        'perioden': perioden,
        'mitarbeiter': mitarbeiter,
    }
    
    return render(request, 'schichtplan/wunsch_perioden_liste.html', context)


@login_required
def wunsch_eingeben(request, periode_id):
    """
    Formular zum Eintragen/Bearbeiten von Wünschen für einen Tag.
    """
    
    
    # Berechtigungsprüfung
    if not hasattr(request.user, 'mitarbeiter'):
        messages.error(request, "❌ Kein Mitarbeiter-Profil gefunden.")
        return redirect('arbeitszeit:dashboard')
    
    mitarbeiter = request.user.mitarbeiter
    gueltige_kennungen = [f'MA{i}' for i in range(1, 16)]
    
    if mitarbeiter.schichtplan_kennung not in gueltige_kennungen:
        messages.error(request, "❌ Nur Mitarbeiter MA1-MA15 können Wünsche eintragen.")
        return redirect('arbeitszeit:dashboard')
    
    periode = get_object_or_404(SchichtwunschPeriode, pk=periode_id)
    
    # Prüfe ob Periode offen ist
    if not periode.ist_offen:
        messages.warning(
            request, 
            f"⚠️ Die Wunschperiode '{periode.name}' ist nicht mehr offen. "
            f"Status: {periode.get_status_display()}"
        )
        return redirect('schichtplan:wunschperioden_liste')
    
    # Datum aus GET-Parameter
    datum_str = request.GET.get('datum')
    if not datum_str:
        messages.error(request, "❌ Kein Datum angegeben.")
        return redirect('schichtplan:wunsch_kalender', periode_id=periode.pk)
    
    try:
        # Datum parsen - mehrere Formate versuchen
        try:
            wunsch_datum = datetime.strptime(datum_str, '%Y-%m-%d').date()
        except ValueError:
            # Versuche deutsches Format
            wunsch_datum = datetime.strptime(datum_str, '%d. %B %Y').date()
    except ValueError:
        messages.error(request, f"❌ Ungültiges Datumsformat: {datum_str}")
        return redirect('schichtplan:wunsch_kalender', periode_id=periode.pk)
    
    # Prüfe ob Datum im Monat liegt
    if wunsch_datum.month != periode.fuer_monat.month or wunsch_datum.year != periode.fuer_monat.year:
        messages.error(request, "❌ Datum liegt nicht im Wunsch-Monat.")
        return redirect('schichtplan:wunsch_kalender', periode_id=periode.pk)
    
    # Lade oder erstelle Wunsch
    wunsch, created = Schichtwunsch.objects.get_or_create(
        periode=periode,
        mitarbeiter=mitarbeiter,
        datum=wunsch_datum,
        defaults={'wunsch': 'tag_bevorzugt'}
    )
    
    if request.method == 'POST':
        wunsch_kategorie = request.POST.get('wunsch')
        begruendung = request.POST.get('begruendung', '')
        
        if wunsch_kategorie:
            wunsch.wunsch = wunsch_kategorie
            wunsch.begruendung = begruendung
            wunsch.save()
            
            messages.success(
                request,
                f"✅ Wunsch für {wunsch_datum.strftime('%d.%m.%Y')} gespeichert: "
                f"{wunsch.get_wunsch_display()}"
            )
            
            return redirect('schichtplan:wunsch_kalender', periode_id=periode.pk)
    
    # Zeige andere Wünsche für diesen Tag (Transparenz!)
    andere_wuensche = Schichtwunsch.objects.filter(
        periode=periode,
        datum=wunsch_datum
    ).exclude(
        mitarbeiter=mitarbeiter
    ).select_related('mitarbeiter').order_by('mitarbeiter__schichtplan_kennung')
    
    context = {
        'periode': periode,
        'wunsch': wunsch,
        'wunsch_datum': wunsch_datum,
        'andere_wuensche': andere_wuensche,
        'wunsch_kategorien': Schichtwunsch.WUNSCH_KATEGORIEN,
    }
    
    return render(request, 'schichtplan/wuensche_eingeben.html', context)



@login_required
def wunsch_ansehen(request, periode_id):
    """
    Zeigt ALLE Wünsche von MA1-MA15 für Transparenz.
    Mitarbeiter sehen Wünsche der Kollegen.
    Schichtplaner sehen alle + Genehmigungsstatus.
    """
    
    
    
    
    # Prüfe Berechtigung
    if not (ist_schichtplaner(request.user) or 
            (hasattr(request.user, 'mitarbeiter') and 
             request.user.mitarbeiter.schichtplan_kennung in 
             [f'MA{i}' for i in range(1, 16)])):
        messages.error(request, "❌ Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')
    
    periode = get_object_or_404(SchichtwunschPeriode, pk=periode_id)
    
    # Generiere alle Tage
    jahr = periode.fuer_monat.year
    monat = periode.fuer_monat.month
    _, anzahl_tage = monthrange(jahr, monat)
    
    tage_im_monat = []
    for tag in range(1, anzahl_tage + 1):
        datum = datetime(jahr, monat, tag).date()
        tage_im_monat.append({
            'datum': datum,
            'wochentag': datum.strftime('%A'),
            'ist_wochenende': datum.weekday() >= 5,
        })
    
    # Lade alle Wünsche von MA1-MA15
    planbare_ma = get_planbare_mitarbeiter().order_by(
        Length('schichtplan_kennung'),
        'schichtplan_kennung'
    )
    
    alle_wuensche = Schichtwunsch.objects.filter(
        mitarbeiter__in=planbare_ma,
        datum__year=jahr,
        datum__month=monat
    ).select_related('mitarbeiter')
    
    # Gruppiere Wünsche: {datum: {mitarbeiter_id: wunsch_obj}}
    wuensche_matrix = defaultdict(dict)
    for wunsch in alle_wuensche:
        wuensche_matrix[wunsch.datum][wunsch.mitarbeiter.pk] = wunsch
    
    # Konflikt-Analyse (wie viele wollen Urlaub/frei pro Tag)
    konflikt_tage = {}
    for datum_obj in tage_im_monat:
        datum = datum_obj['datum']
        wuensche_am_tag = alle_wuensche.filter(datum=datum)
        
        urlaub_count = wuensche_am_tag.filter(wunsch='urlaub').count()
        frei_count = wuensche_am_tag.filter(wunsch='gar_nichts').count()
        
        gesamt_frei = urlaub_count + frei_count
        
        if gesamt_frei >= 3:  # Kritisch!
            konflikt_tage[datum] = {
                'urlaub': urlaub_count,
                'frei': frei_count,
                'gesamt': gesamt_frei,
                'level': 'danger' if gesamt_frei >= 5 else 'warning'
            }
    
    context = {
        'periode': periode,
        'tage_im_monat': tage_im_monat,
        'mitarbeiter_liste': planbare_ma,
        'wuensche_matrix': dict(wuensche_matrix),
        'konflikt_tage': konflikt_tage,
        'ist_planer': ist_schichtplaner(request.user),
        'eigener_mitarbeiter': request.user.mitarbeiter if hasattr(request.user, 'mitarbeiter') else None,
    }
    
    return render(request, 'schichtplan/wunsch_ansehen.html', context)

@login_required
def wuensche_genehmigen(request, periode_id):
    """
    Schichtplaner genehmigt Wünsche die Genehmigung benötigen.
    (Urlaub + gar_nichts)
    """
    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung.")
        return redirect('schichtplan:dashboard')
    
    periode = get_object_or_404(SchichtwunschPeriode, pk=periode_id)
    
    # Lade alle Wünsche die Genehmigung benötigen
    offene_wuensche = Schichtwunsch.objects.filter(
        periode=periode,
        benoetigt_genehmigung=True,
        genehmigt=False
    ).select_related('mitarbeiter').order_by('datum', 'mitarbeiter__schichtplan_kennung')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        wunsch_id = request.POST.get('wunsch_id')
        
        if action and wunsch_id:
            wunsch = get_object_or_404(Schichtwunsch, pk=wunsch_id)
            
            if action == 'genehmigen':
                wunsch.genehmigt = True
                wunsch.genehmigt_von = request.user
                wunsch.genehmigt_am = timezone.now()
                wunsch.save()
                
                messages.success(
                    request, 
                    f"✅ Wunsch von {wunsch.mitarbeiter.vollname} am {wunsch.datum} genehmigt!"
                )
            
            elif action == 'ablehnen':
                wunsch.delete()
                messages.info(
                    request,
                    f"ℹ️ Wunsch von {wunsch.mitarbeiter.vollname} am {wunsch.datum} abgelehnt."
                )
            
            return redirect('schichtplan:wuensche_genehmigen', periode_id=periode.pk)
    
    # Statistiken
    stats = {
        'offen': offene_wuensche.count(),
        'genehmigt': Schichtwunsch.objects.filter(
            periode=periode,
            genehmigt=True
        ).count(),
        'gesamt': Schichtwunsch.objects.filter(periode=periode).count(),
    }
    
    context = {
        'periode': periode,
        'offene_wuensche': offene_wuensche,
        'stats': stats,
    }
    
    return render(request, 'schichtplan/wuensche_genehmigen.html', context)

@login_required
def wunsch_kalender(request, periode_id):
    """
    Kalenderansicht aller Wünsche einer Periode.
    TRANSPARENZ: Alle MA1-MA15 sehen die Wünsche der anderen!
    """
    
    import calendar
    from datetime import date, timedelta
    
    # Berechtigungsprüfung
    if not hasattr(request.user, 'mitarbeiter'):
        messages.error(request, "❌ Kein Mitarbeiter-Profil gefunden.")
        return redirect('arbeitszeit:dashboard')
    
    mitarbeiter = request.user.mitarbeiter
    gueltige_kennungen = [f'MA{i}' for i in range(1, 16)]
    
    if not (ist_schichtplaner(request.user) or mitarbeiter.schichtplan_kennung in gueltige_kennungen):
        messages.error(request, "❌ Nur MA1-MA15 können Wünsche einsehen.")
        return redirect('arbeitszeit:dashboard')
    
    # Lade Periode
    periode = get_object_or_404(SchichtwunschPeriode, pk=periode_id)
    
    # Lade ALLE MA1-MA15
    planbare_ma = get_planbare_mitarbeiter()
    
    print(f"\n🔍 DEBUG wunsch_kalender:")
    print(f"   Periode: {periode.name}")
    print(f"   Monat: {periode.fuer_monat}")
    print(f"   Anzahl MA: {planbare_ma.count()}")
    
    # Lade alle Wünsche für diese Periode
    
    alle_wuensche = Schichtwunsch.objects.filter(
        periode=periode,
        mitarbeiter__in=planbare_ma
    ).select_related('mitarbeiter')
    
    print(f"   Anzahl Wünsche: {alle_wuensche.count()}")
    
    # Gruppiere Wünsche nach Datum
    wuensche_nach_datum = defaultdict(list)
    for wunsch in alle_wuensche:
        wuensche_nach_datum[wunsch.datum].append(wunsch)
    
    # Erstelle Kalenderstruktur
    monat_start = date(periode.fuer_monat.year, periode.fuer_monat.month, 1)
    letzter_tag = calendar.monthrange(monat_start.year, monat_start.month)[1]
    monat_ende = date(monat_start.year, monat_start.month, letzter_tag)
    
    print(f"   Zeitraum: {monat_start} bis {monat_ende}")
    
    kalender_daten = []
    current_date = monat_start
    
    while current_date <= monat_ende:
        tag_wuensche = wuensche_nach_datum.get(current_date, [])
        
        # Berechne Konflikte
        urlaube = sum(1 for w in tag_wuensche if w.wunsch == 'urlaub')
        gar_nichts = sum(1 for w in tag_wuensche if w.wunsch == 'gar_nichts')
        konflikt = None
        
        if urlaube + gar_nichts > 3:
            konflikt = {
                'typ': 'zu_viele_frei',
                'anzahl': urlaube + gar_nichts,
            }
        
        kalender_daten.append({
            'datum': current_date,
            'wochentag': calendar.day_name[current_date.weekday()],
            'ist_wochenende': current_date.weekday() >= 5,
            'wuensche': tag_wuensche,
            'konflikt': konflikt,
            'hat_eigenen_wunsch': any(w.mitarbeiter == mitarbeiter for w in tag_wuensche),
        })
        
        current_date += timedelta(days=1)
    
    print(f"   Anzahl Kalendertage: {len(kalender_daten)}")
    
    context = {
        'periode': periode,
        'kalender_daten': kalender_daten,
        'mitarbeiter': mitarbeiter,
        'alle_mitarbeiter': planbare_ma,
        'monat_name': calendar.month_name[monat_start.month],
    }
    # DEBUG vor return
    print(f"\n🔍 DEBUG Context:")
    print(f"   Anzahl kalender_daten: {len(kalender_daten)}")
    print(f"   Anzahl alle_mitarbeiter: {planbare_ma.count()}")
    print(f"   Erste 3 Tage:")
    for tag in kalender_daten[:3]:
        print(f"      {tag['datum']}: {len(tag['wuensche'])} Wünsche")
        for w in tag['wuensche']:
            print(f"         - {w.mitarbeiter.schichtplan_kennung}: {w.get_wunsch_display()}")
    
    context = {
        'periode': periode,
        'kalender_daten': kalender_daten,
        'mitarbeiter': mitarbeiter,
        'alle_mitarbeiter': planbare_ma,
        'monat_name': calendar.month_name[monat_start.month],
    }
    
    return render(request, 'schichtplan/wunsch_kalender.html', context)
    
    


@login_required
def wunsch_loeschen(request, wunsch_id):
    """
    Löscht einen eigenen Wunsch.
    Mitarbeiter können nur ihre eigenen Wünsche löschen.
    """
    
    
    wunsch = get_object_or_404(Schichtwunsch, pk=wunsch_id)
    
    # Prüfe Berechtigung - Nur eigener Wunsch!
    if not hasattr(request.user, 'mitarbeiter'):
        messages.error(request, "❌ Kein Mitarbeiter-Profil gefunden.")
        return redirect('arbeitszeit:dashboard')
    
    if wunsch.mitarbeiter != request.user.mitarbeiter:
        messages.error(request, "❌ Sie können nur Ihre eigenen Wünsche löschen!")
        return redirect('schichtplan:wunschperioden_liste')
    
    periode_id = wunsch.periode.pk if wunsch.periode else None
    
    if request.method == 'POST':
        wunsch.delete()
        messages.success(request, "✅ Wunsch wurde gelöscht.")
        
        if periode_id:
            return redirect('schichtplan:wunsch_kalender', periode_id=periode_id)
        else:
            return redirect('schichtplan:wunschperioden_liste')
    
    # GET: Zeige Bestätigungsseite
    context = {
        'wunsch': wunsch,
    }
    
    return render(request, 'schichtplan/wunsch_loeschen_confirm.html', context)


@login_required
def wuensche_schichtplaner_uebersicht(request, periode_id):
    """
    Übersicht aller Wünsche für Schichtplaner.
    Zeigt Statistiken und Liste aller Wünsche von MA1-MA15.
    """
    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung für diese Seite.")
        return redirect('arbeitszeit:dashboard')
    
    
 
    
    periode = get_object_or_404(SchichtwunschPeriode, pk=periode_id)
    
    # Lade alle Wünsche von MA1-MA15
    planbare_ma = get_planbare_mitarbeiter()
    
    alle_wuensche = Schichtwunsch.objects.filter(
        periode=periode,
        mitarbeiter__in=planbare_ma
    ).select_related('mitarbeiter').order_by('datum', 'mitarbeiter__schichtplan_kennung')
    
    # Statistiken
    stats = {
        'gesamt': alle_wuensche.count(),
        'urlaube': alle_wuensche.filter(wunsch='urlaub').count(),
        'gar_nichts': alle_wuensche.filter(wunsch='gar_nichts').count(),
        'offen_genehmigung': alle_wuensche.filter(
            benoetigt_genehmigung=True,
            genehmigt=False
        ).count(),
        'genehmigt': alle_wuensche.filter(genehmigt=True).count(),
    }
    
    # Gruppiere nach Mitarbeiter
    wuensche_nach_ma = defaultdict(list)
    for wunsch in alle_wuensche:
        wuensche_nach_ma[wunsch.mitarbeiter].append(wunsch)
    
    # Sortiere Mitarbeiter nach Kennung
    from django.db.models.functions import Length
    sortierte_ma = sorted(
        wuensche_nach_ma.keys(),
        key=lambda ma: (len(ma.schichtplan_kennung or ''), ma.schichtplan_kennung or '')
    )
    
    context = {
        'periode': periode,
        'wuensche_nach_ma': dict(wuensche_nach_ma),
        'sortierte_ma': sortierte_ma,
        'stats': stats,
        'alle_mitarbeiter': planbare_ma,
    }
    
    return render(request, 'schichtplan/wuensche_schichtplaner_uebersicht.html', context)


@login_required
def wunsch_genehmigen(request, wunsch_id):
    """
    Genehmigt oder lehnt einen einzelnen Wunsch ab.
    Nur für Schichtplaner.
    """
    if not ist_schichtplaner(request.user):
        messages.error(request, "❌ Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')
    
    
    
    wunsch = get_object_or_404(Schichtwunsch, pk=wunsch_id)
    
    if request.method == 'POST':
        aktion = request.POST.get('aktion')
        
        if aktion == 'genehmigen':
            wunsch.genehmigt = True
            wunsch.genehmigt_von = request.user
            wunsch.genehmigt_am = timezone.now()
            wunsch.save()
            
            messages.success(
                request,
                f"✅ Wunsch von {wunsch.mitarbeiter.vollname} wurde genehmigt."
            )
        
        elif aktion == 'ablehnen':
            # Ablehnen = Wunsch löschen oder Flag setzen
            wunsch.genehmigt = False
            wunsch.genehmigt_von = None
            wunsch.genehmigt_am = None
            wunsch.save()
            
            messages.info(
                request,
                f"ℹ️ Wunsch von {wunsch.mitarbeiter.vollname} wurde abgelehnt."
            )
        
        # Redirect zurück zur Übersicht
        if wunsch.periode:
            return redirect('schichtplan:wuensche_schichtplaner_uebersicht', periode_id=wunsch.periode.pk)
        else:
            return redirect('schichtplan:dashboard')
    
    # GET: Zeige Genehmigungsformular
    context = {
        'wunsch': wunsch,
    }
    
    return render(request, 'schichtplan/wunsch_genehmigen.html', context)
