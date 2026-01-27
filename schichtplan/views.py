
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count
from django.http import JsonResponse
from datetime import datetime, timedelta
from calendar import monthcalendar, day_name
from django.utils import timezone

from arbeitszeit.models import Mitarbeiter
from .models import Schichtplan, Schicht, Schichttyp, Schichtwunsch, SchichtwunschPeriode
from .forms import ExcelImportForm, SchichtplanForm, SchichtForm

from .utils.excel_import import SchichtplanImporter
import tempfile
from .utils.excel_import import SchichtplanImporter

@login_required
def excel_import_view(request, pk):
    schichtplan = get_object_or_404(Schichtplan, pk=pk)

    if not ist_schichtplaner(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('schichtplan:dashboard')

    if request.method == 'POST':
        form = ExcelImportForm(request.POST, request.FILES)

        if form.is_valid():
            excel_file = request.FILES['excel_file']

            # Temporäre Datei speichern
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                for chunk in excel_file.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            # Import starten
            importer = SchichtplanImporter()
            importer.import_excel_mit_zuordnung(tmp_path, schichtplan)

            messages.success(request, "✅ Excel-Datei erfolgreich importiert!")
            return redirect('schichtplan:detail', pk=schichtplan.pk)
    else:
        form = ExcelImportForm()

    return render(request, 'schichtplan/excel_import.html', {'form': form, 'schichtplan': schichtplan})



def ist_schichtplaner(user):
    """Prüft ob User Schichtplaner ist"""
    return (
        user.is_staff or 
        (hasattr(user, 'mitarbeiter') and user.mitarbeiter.rolle == 'schichtplaner')
    )


@login_required
def planer_dashboard(request):
    """
    Dashboard für Schichtplaner
    Zeigt alle Schichtpläne in der Übersicht
    """
    # Nur für Schichtplaner
    if not ist_schichtplaner(request.user):
        messages.error(request, "Keine Berechtigung für diese Seite.")
        return redirect('arbeitszeit:dashboard')
    
    # Alle Schichtpläne
    schichtplaene = Schichtplan.objects.all().order_by('-start_datum')
    
    # Statistiken
    aktive_plaene = schichtplaene.filter(status='veroeffentlicht').count()
    entwuerfe = schichtplaene.filter(status='entwurf').count()
    
    # Mitarbeiter-Statistik
    mitarbeiter_gesamt = Mitarbeiter.objects.filter(aktiv=True).count()
    mitarbeiter_zugeordnet = Mitarbeiter.objects.filter(
        aktiv=True
    ).exclude(schichtplan_kennung='').count()
    
    context = {
        'schichtplaene': schichtplaene,
        'aktive_plaene': aktive_plaene,
        'entwuerfe': entwuerfe,
        'mitarbeiter_gesamt': mitarbeiter_gesamt,
        'mitarbeiter_zugeordnet': mitarbeiter_zugeordnet,
    }
    
    return render(request, 'schichtplan/planer_dashboard.html', context)


@login_required
def schichtplan_detail(request, pk):
    """
    Detail-Ansicht eines Schichtplans
    Zeigt Kalender mit allen Schichten
    """
    schichtplan = get_object_or_404(Schichtplan, pk=pk)
    
    # Berechtigung prüfen
    if not ist_schichtplaner(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')
    
    # Alle Schichten des Plans
    schichten = schichtplan.schichten.select_related(
        'mitarbeiter', 'schichttyp'
    ).order_by('datum', 'schichttyp__start_zeit')
    
    # Kalender-Daten vorbereiten
    kalender_daten = {}
    current_date = schichtplan.start_datum
    
    while current_date <= schichtplan.ende_datum:
        tag_schichten = schichten.filter(datum=current_date)
        kalender_daten[current_date] = {
            'datum': current_date,
            'wochentag': day_name[current_date.weekday()],
            'schichten': tag_schichten,
            'ist_wochenende': current_date.weekday() >= 5,
        }
        current_date += timedelta(days=1)
    
    # Mitarbeiter mit Schichtzahlen
    mitarbeiter_stats = Mitarbeiter.objects.filter(
        schichten__schichtplan=schichtplan
    ).annotate(
        anzahl_schichten=Count('schichten')
    ).order_by('-anzahl_schichten')
    
    context = {
        'schichtplan': schichtplan,
        'kalender_daten': kalender_daten,
        'mitarbeiter_stats': mitarbeiter_stats,
        'schichttypen': Schichttyp.objects.filter(aktiv=True),
    }
    
    return render(request, 'schichtplan/schichtplan_detail.html', context)


@login_required
def schichtplan_erstellen(request):
    """
    Neuen Schichtplan erstellen
    """
    if not ist_schichtplaner(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')
    
    if request.method == 'POST':
        form = SchichtplanForm(request.POST)
        
        if form.is_valid():
            schichtplan = form.save(commit=False)
            schichtplan.erstellt_von = request.user
            schichtplan.save()
            
            messages.success(
                request, 
                f"Schichtplan '{schichtplan.name}' erfolgreich erstellt!"
            )
            
            return redirect('schichtplan:detail', pk=schichtplan.pk)
    else:
        form = SchichtplanForm()
    
    context = {
        'form': form,
    }
    
    return render(request, 'schichtplan/schichtplan_erstellen.html', context)


@login_required
def excel_analyse_view(request):
    """
    Analysiert Excel-Datei vor dem Import
    Zeigt Vorschau ohne zu importieren
    """
    if not ist_schichtplaner(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')
    
    if request.method == 'POST':
        form = ExcelImportForm(request.POST, request.FILES)
        
        if form.is_valid():
            excel_file = request.FILES['excel_file']
            
            # Analyse durchführen (OHNE Import)
            stats = analyze_excel_file(excel_file)
            
            context = {
                'stats': stats,
                'form': form,
            }
            
            return render(request, 'schichtplan/excel_analyse.html', context)
    else:
        form = ExcelImportForm()
    
    context = {
        'form': form,
    }
    
    return render(request, 'schichtplan/excel_analyse.html', context)


@login_required
def mitarbeiter_uebersicht(request):
    """Mitarbeiter-Übersicht für Schichtplaner"""
    
    # Berechtigung prüfen
    if not (request.user.is_staff or 
            (hasattr(request.user, 'mitarbeiter') and 
             request.user.mitarbeiter.rolle == 'schichtplaner')):
        messages.error(request, "Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')
    
    # ALLE Schichtplaner sehen nur ihre eigene Abteilung (auch wenn is_staff)
    if hasattr(request.user, 'mitarbeiter'):
        eigene_abteilung = request.user.mitarbeiter.abteilung
        mitarbeiter = Mitarbeiter.objects.filter(
            aktiv=True,
            abteilung=eigene_abteilung
        )
    else:
        # Nur echte Superuser ohne Mitarbeiter-Profil sehen alle
        mitarbeiter = Mitarbeiter.objects.filter(aktiv=True)
    
    # Statistiken berechnen
    stats = {
        'gesamt': mitarbeiter.count(),
        'zugeordnet': mitarbeiter.exclude(schichtplan_kennung='').count(),
        'nicht_zugeordnet': mitarbeiter.filter(schichtplan_kennung='').count(),
        'dauerkrank': mitarbeiter.filter(verfuegbarkeit='dauerkrank').count(),
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
def schicht_zuweisen(request, schichtplan_pk):
    """
    Schicht manuell zuweisen (AJAX oder Form)
    """
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
                messages.success(request, "Schicht erfolgreich zugewiesen!")
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'schicht_id': schicht.pk,
                    })
                
                return redirect('schichtplan:detail', pk=schichtplan.pk)
                
            except Exception as e:
                messages.error(request, f"Fehler beim Speichern: {e}")
                
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
    """
    Schicht löschen
    """
    schicht = get_object_or_404(Schicht, pk=pk)
    
    if not ist_schichtplaner(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('schichtplan:dashboard')
    
    schichtplan_pk = schicht.schichtplan.pk
    
    if request.method == 'POST':
        schicht.delete()
        messages.success(request, "Schicht wurde gelöscht.")
        return redirect('schichtplan:detail', pk=schichtplan_pk)
    
    context = {
        'schicht': schicht,
    }
    
    return render(request, 'schichtplan/schicht_loeschen_confirm.html', context)

@login_required
def wuensche_genehmigen(request, periode_id):
    """Schichtplaner genehmigt Urlaub und 'gar nichts' Wünsche"""
    
    if not ist_schichtplaner(request.user):
        messages.error(request, "Keine Berechtigung.")
        return redirect('schichtplan:dashboard')
    
    periode = get_object_or_404(SchichtwunschPeriode, pk=periode_id)

