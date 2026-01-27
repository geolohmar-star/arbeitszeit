"""
Django Views für Arbeitszeitverwaltung
"""
from pydoc import doc
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Sum
from datetime import datetime, timedelta

from .models import (
    Mitarbeiter, Arbeitszeitvereinbarung, Tagesarbeitszeit,
    ArbeitszeitHistorie, Zeiterfassung, Urlaubsanspruch
)
from .forms import ArbeitszeitvereinbarungForm, TagesarbeitszeitFormSet
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.shortcuts import render, redirect
from django.contrib import messages
from .forms import RegisterForm
from .models import Mitarbeiter






@login_required
def dashboard(request):
    """Dashboard mit Routing für verschiedene Rollen"""
    
    # Prüfe Mitarbeiter-Rolle
    if hasattr(request.user, 'mitarbeiter'):
        rolle = request.user.mitarbeiter.rolle
        
        # Sachbearbeiter → Admin-Dashboard
        if rolle == 'sachbearbeiter':
            return redirect('arbeitszeit:admin_dashboard')
        
        # Schichtplaner → Schichtplan-Dashboard
        if rolle == 'schichtplaner':
            return redirect('schichtplan:dashboard')
    
    # Normale Mitarbeiter → Mitarbeiter-Dashboard
    # Mitarbeiter-Profil holen oder erstellen
    try:
        mitarbeiter = request.user.mitarbeiter
    except Mitarbeiter.DoesNotExist:
        from datetime import date
        mitarbeiter = Mitarbeiter.objects.create(
            user=request.user,
            personalnummer=f'MA{request.user.id:04d}',
            vorname=request.user.first_name or 'Vorname',
            nachname=request.user.last_name or 'Nachname',
            abteilung='Allgemein',
            standort='siegburg',
            eintrittsdatum=date.today(),
            aktiv=True
        )
        messages.info(request, "Ihr Mitarbeiter-Profil wurde erstellt.")
    
    # Aktuelle Vereinbarung
    aktuelle_vereinbarung = mitarbeiter.get_aktuelle_vereinbarung()
    
    # Letzte Zeiterfassungen
    letzte_erfassungen = mitarbeiter.zeiterfassungen.all()[:10]
    
    # Urlaubsanspruch für aktuelles Jahr
    aktuelles_jahr = timezone.now().year
    try:
        urlaubsanspruch = mitarbeiter.urlaubsansprueche.get(jahr=aktuelles_jahr)
    except Urlaubsanspruch.DoesNotExist:
        urlaubsanspruch = None
    
    # Alle Vereinbarungen
    alle_vereinbarungen = mitarbeiter.arbeitszeitvereinbarungen.all()[:5]
    
    context = {
        'mitarbeiter': mitarbeiter,
        'aktuelle_vereinbarung': aktuelle_vereinbarung,
        'letzte_erfassungen': letzte_erfassungen,
        'urlaubsanspruch': urlaubsanspruch,
        'alle_vereinbarungen': alle_vereinbarungen,
        'user': request.user,
    }
       
    return render(request, 'arbeitszeit/dashboard.html', context)


@login_required
def vereinbarung_erstellen(request):
    """Neue Arbeitszeitvereinbarung erstellen"""
    try:
        mitarbeiter = request.user.mitarbeiter
    except Mitarbeiter.DoesNotExist:
        messages.error(request, "Sie sind keinem Mitarbeiter zugeordnet.")
        return redirect('admin:index')
    
    if request.method == 'POST':
        antragsart = request.POST.get('antragsart')
        
        # Basisvereinbarung erstellen
        vereinbarung = Arbeitszeitvereinbarung(
            mitarbeiter=mitarbeiter,
            antragsart=antragsart,
            gueltig_ab=request.POST.get(f"{antragsart}_datum"),
            telearbeit=request.POST.get(f"{antragsart}_telearbeit") == 'on',
            status='beantragt'
        )
        
        # WICHTIG: Bei Beendigung keine Arbeitszeit-Felder setzen!
        if antragsart == 'beendigung':
            # Bei Beendigung nur Beendigungsdatum setzen
            vereinbarung.beendigung_beantragt = True
            vereinbarung.beendigung_datum = vereinbarung.gueltig_ab
        else:
            # Nur bei NICHT-Beendigung Arbeitszeit-Felder verarbeiten
            arbeitszeit_typ = request.POST.get('arbeitszeit_typ')
            vereinbarung.arbeitszeit_typ = arbeitszeit_typ
            
            if arbeitszeit_typ == 'regelmaessig':
                # Regelmäßige Arbeitszeit
                prefix = antragsart
                vereinbarung.wochenstunden = request.POST.get(f"{prefix}_stunden")
        
        vereinbarung.save()
        
        # Nur bei NICHT-Beendigung und individuell: Tagesarbeitszeiten speichern
        if antragsart != 'beendigung' and request.POST.get('arbeitszeit_typ') == 'individuell':
            prefix = antragsart
            tage = ['montag', 'dienstag', 'mittwoch', 'donnerstag', 'freitag']
            
            for tag in tage:
                zeitwert = request.POST.get(f"{prefix}_{tag}")
                if zeitwert:
                    Tagesarbeitszeit.objects.create(
                        vereinbarung=vereinbarung,
                        wochentag=tag,
                        zeitwert=int(zeitwert)
                    )
        
        # Gültigkeitsdatum (nur bei NICHT-Beendigung)
        if antragsart != 'beendigung':
            gueltig_bis = request.POST.get('gueltig_bis')
            if gueltig_bis:
                vereinbarung.gueltig_bis = gueltig_bis
        
        vereinbarung.save()
        
        # Historie erstellen
        ArbeitszeitHistorie.objects.create(
            vereinbarung=vereinbarung,
            aenderung_durch=request.user,
            alter_status='entwurf',
            neuer_status='beantragt',
            bemerkung=f'{vereinbarung.get_antragsart_display()} erstellt und beantragt'
        )
        
        # Erfolgsmeldu ng angepasst an Antragsart
        if antragsart == 'beendigung':
            messages.success(request, 'Beendigung wurde erfolgreich beantragt.')
        else:
            messages.success(request, 'Arbeitszeitvereinbarung wurde erfolgreich beantragt.')
        
        return redirect('arbeitszeit:dashboard')
    
    context = {
        'mitarbeiter': mitarbeiter,
    }
    
    return render(request, 'arbeitszeit/vereinbarung_form.html', context)

@login_required
def vereinbarung_detail(request, pk):
    """Details einer Arbeitszeitvereinbarung anzeigen"""
    from django.db.models import Case, When, IntegerField
    
    try:
        mitarbeiter = request.user.mitarbeiter
    except Mitarbeiter.DoesNotExist:
        messages.error(request, "Sie sind keinem Mitarbeiter zugeordnet.")
        return redirect('admin:index')
    
    vereinbarung = get_object_or_404(
        Arbeitszeitvereinbarung,
        pk=pk,
        mitarbeiter=mitarbeiter
    )
    
    # Tagesarbeitszeiten mit korrekter Sortierung
    tagesarbeitszeiten = vereinbarung.tagesarbeitszeiten.annotate(
        sort_order=Case(
            When(wochentag='montag', then=1),
            When(wochentag='dienstag', then=2),
            When(wochentag='mittwoch', then=3),
            When(wochentag='donnerstag', then=4),
            When(wochentag='freitag', then=5),
            When(wochentag='samstag', then=6),
            When(wochentag='sonntag', then=7),
            default=99,
            output_field=IntegerField(),
        )
    ).order_by('sort_order')
    
    # Historie laden
    historie = vereinbarung.historie.all()
    
    context = {
        'vereinbarung': vereinbarung,
        'tagesarbeitszeiten': tagesarbeitszeiten,
        'historie': historie,
    }
    
    return render(request, 'arbeitszeit/vereinbarung_detail.html', context)
    
    # Historie laden
    historie = vereinbarung.historie.all()
    
    context = {
        'vereinbarung': vereinbarung,
        'tagesarbeitszeiten': tagesarbeitszeiten,
        'historie': historie,
    }
    
    return render(request, 'arbeitszeit/vereinbarung_detail.html', context)


@login_required
def vereinbarung_liste(request):
    """Liste aller Vereinbarungen eines Mitarbeiters"""
    try:
        mitarbeiter = request.user.mitarbeiter
    except Mitarbeiter.DoesNotExist:
        messages.error(request, "Sie sind keinem Mitarbeiter zugeordnet.")
        return redirect('admin:index')
    
    vereinbarungen = mitarbeiter.arbeitszeitvereinbarungen.all()
    
    # Filter nach Status
    status_filter = request.GET.get('status')
    if status_filter:
        vereinbarungen = vereinbarungen.filter(status=status_filter)
    
    context = {
        'mitarbeiter': mitarbeiter,
        'vereinbarungen': vereinbarungen,
        'status_filter': status_filter,
    }
    
    return render(request, 'arbeitszeit/vereinbarung_liste.html', context)


@login_required
def zeiterfassung_erstellen(request):
    """Tageszeit erfassen"""
    try:
        mitarbeiter = request.user.mitarbeiter
    except Mitarbeiter.DoesNotExist:
        messages.error(request, "Sie sind keinem Mitarbeiter zugeordnet.")
        return redirect('admin:index')
    
    # Standarddatum: heute
    datum = request.POST.get('datum', timezone.now().date())
    
    if request.method == 'POST':
        Zeiterfassung.objects.update_or_create(
            mitarbeiter=mitarbeiter,
            datum=datum,
            defaults={
                'arbeitsbeginn': request.POST.get('arbeitsbeginn') or None,
                'arbeitsende': request.POST.get('arbeitsende') or None,
                'pause_minuten': int(request.POST.get('pause_minuten', 0)),
                'art': request.POST.get('art', 'buero'),
                'bemerkung': request.POST.get('bemerkung', ''),
            }
        )
        
        messages.success(request, 'Zeiterfassung wurde gespeichert.')
        return redirect('arbeitszeit:zeiterfassung_uebersicht')
    
    # Vorhandene Erfassung laden
    try:
        erfassung = Zeiterfassung.objects.get(mitarbeiter=mitarbeiter, datum=datum)
    except Zeiterfassung.DoesNotExist:
        erfassung = None
    
    context = {
        'mitarbeiter': mitarbeiter,
        'datum': datum,
        'erfassung': erfassung,
    }
    
    return render(request, 'arbeitszeit/zeiterfassung_form.html', context)


@login_required
def zeiterfassung_uebersicht(request):
    """Übersicht der Zeiterfassungen"""
    try:
        mitarbeiter = request.user.mitarbeiter
    except Mitarbeiter.DoesNotExist:
        messages.error(request, "Sie sind keinem Mitarbeiter zugeordnet.")
        return redirect('admin:index')
    
    # Datum-Filter
    jahr = int(request.GET.get('jahr', timezone.now().year))
    monat = int(request.GET.get('monat', timezone.now().month))
    
    # Erfassungen für den Monat
    erfassungen = mitarbeiter.zeiterfassungen.filter(
        datum__year=jahr,
        datum__month=monat
    )
    
    # Statistiken
    gesamt_minuten = erfassungen.aggregate(
        total=Sum('arbeitszeit_minuten')
    )['total'] or 0
    
    gesamt_stunden = gesamt_minuten // 60
    gesamt_min = gesamt_minuten % 60
    
    context = {
        'mitarbeiter': mitarbeiter,
        'erfassungen': erfassungen,
        'jahr': jahr,
        'monat': monat,
        'gesamt_arbeitszeit': f"{gesamt_stunden}:{gesamt_min:02d}h",
    }
    
    return render(request, 'arbeitszeit/zeiterfassung_uebersicht.html', context)


# Admin/Vorgesetzten-Views
@login_required
def admin_dashboard(request):
    """Admin Dashboard mit Übersicht und Statistiken"""
    if not request.user.is_staff:
        messages.error(request, "Sie haben keine Berechtigung für diese Seite.")
        return redirect('arbeitszeit:dashboard')
    
    from django.utils import timezone
    from datetime import datetime, timedelta
    
    # Statistiken sammeln
    
    # Offene Anträge
    offene_antraege = Arbeitszeitvereinbarung.objects.filter(
        status='beantragt'
    ).count()
    
    # Gesamt Mitarbeiter
    gesamt_mitarbeiter = Mitarbeiter.objects.filter(aktiv=True).count()
    
    # Genehmigte Vereinbarungen diesen Monat
    heute = timezone.now()
    monatsanfang = heute.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    genehmigte_vereinbarungen = Arbeitszeitvereinbarung.objects.filter(
        status='genehmigt',
        genehmigt_am__gte=monatsanfang
    ).count()
    
    # Aktive Vereinbarungen
    aktive_vereinbarungen = Arbeitszeitvereinbarung.objects.filter(
        status='aktiv'
    ).count()
    
    # Letzte Aktivitäten (neueste Anträge)
    letzte_aktivitaeten = Arbeitszeitvereinbarung.objects.filter(
        created_at__gte=heute.replace(hour=0, minute=0, second=0, microsecond=0)
    ).order_by('-created_at')[:5]
    
    # Mitarbeiter nach Standort
    mitarbeiter_siegburg = Mitarbeiter.objects.filter(
        aktiv=True,
        standort='siegburg'
    ).count()
    
    mitarbeiter_bonn = Mitarbeiter.objects.filter(
        aktiv=True,
        standort='bonn'
    ).count()
    
    context = {
        'offene_antraege': offene_antraege,
        'gesamt_mitarbeiter': gesamt_mitarbeiter,
        'genehmigte_vereinbarungen': genehmigte_vereinbarungen,
        'aktive_vereinbarungen': aktive_vereinbarungen,
        'letzte_aktivitaeten': letzte_aktivitaeten,
        'mitarbeiter_siegburg': mitarbeiter_siegburg,
        'mitarbeiter_bonn': mitarbeiter_bonn,
    }
    
    return render(request, 'arbeitszeit/admin_dashboard.html', context)

@login_required
def admin_vereinbarungen_genehmigen(request):
    """Liste offener UND aller Anträge zur Genehmigung"""
    if not request.user.is_staff:
        messages.error(request, "Sie haben keine Berechtigung für diese Seite.")
        return redirect('arbeitszeit:dashboard')
    
    # Offene Anträge
    offene_antraege = Arbeitszeitvereinbarung.objects.filter(
        status='beantragt'
    ).select_related('mitarbeiter').order_by('-created_at')
    
    # Alle Vereinbarungen
    alle_vereinbarungen = Arbeitszeitvereinbarung.objects.all(
    ).select_related('mitarbeiter').order_by('-created_at')
    
    context = {
        'offene_antraege': offene_antraege,
        'alle_vereinbarungen': alle_vereinbarungen,
    }
    
    return render(request, 'arbeitszeit/admin_vereinbarungen.html', context)


@login_required
def admin_vereinbarung_genehmigen(request, pk):
    """Einzelne Vereinbarung genehmigen oder ablehnen"""
    from django.db.models import Case, When, IntegerField
    
    if not request.user.is_staff:
        messages.error(request, "Sie haben keine Berechtigung für diese Aktion.")
        return redirect('arbeitszeit:dashboard')
    
    vereinbarung = get_object_or_404(Arbeitszeitvereinbarung, pk=pk)
    
    if request.method == 'POST':
        aktion = request.POST.get('aktion')
        bemerkung = request.POST.get('bemerkung', '')
        
        alter_status = vereinbarung.status
        
        if aktion == 'genehmigen':
            vereinbarung.status = 'genehmigt'
            vereinbarung.genehmigt_von = request.user
            vereinbarung.genehmigt_am = timezone.now()
            messages.success(request, 'Vereinbarung wurde genehmigt.')
        
        elif aktion == 'aktivieren':
            vereinbarung.status = 'aktiv'
            messages.success(request, 'Vereinbarung wurde aktiviert.')
        
        elif aktion == 'ablehnen':
            vereinbarung.status = 'abgelehnt'
            messages.warning(request, 'Vereinbarung wurde abgelehnt.')
        
        vereinbarung.save()
        
        # Historie erstellen
        ArbeitszeitHistorie.objects.create(
            vereinbarung=vereinbarung,
            aenderung_durch=request.user,
            alter_status=alter_status,
            neuer_status=vereinbarung.status,
            bemerkung=bemerkung
        )
        
        return redirect('arbeitszeit:admin_vereinbarungen')
    
    # Tagesarbeitszeiten mit korrekter Sortierung
    tagesarbeitszeiten = vereinbarung.tagesarbeitszeiten.annotate(
        sort_order=Case(
            When(wochentag='montag', then=1),
            When(wochentag='dienstag', then=2),
            When(wochentag='mittwoch', then=3),
            When(wochentag='donnerstag', then=4),
            When(wochentag='freitag', then=5),
            When(wochentag='samstag', then=6),
            When(wochentag='sonntag', then=7),
            default=99,
            output_field=IntegerField(),
        )
    ).order_by('sort_order')
    
    context = {
        'vereinbarung': vereinbarung,
        'tagesarbeitszeiten': tagesarbeitszeiten,
    }
    
    return render(request, 'arbeitszeit/admin_vereinbarung_detail.html', context)


@login_required
def mitarbeiter_uebersicht(request):
    """Übersicht aller Mitarbeiter (nur für Vorgesetzte)"""
    
    # Berechtigung prüfen
    if not request.user.is_staff:
        # Prüfe ob Schichtplaner
        if not (hasattr(request.user, 'mitarbeiter') and 
                request.user.mitarbeiter.rolle == 'schichtplaner'):
            messages.error(request, "Sie haben keine Berechtigung für diese Seite.")
            return redirect('arbeitszeit:dashboard')
    
    # Mitarbeiter filtern
    if request.user.is_staff:
        # Admins sehen alle Mitarbeiter
        mitarbeiter_liste = Mitarbeiter.objects.filter(aktiv=True)
    else:
        # Schichtplaner sehen nur ihre eigene Abteilung
        eigene_abteilung = request.user.mitarbeiter.abteilung
        mitarbeiter_liste = Mitarbeiter.objects.filter(
            aktiv=True,
            abteilung=eigene_abteilung
        )
    
    # Filter nach Abteilung (für Admins)
    abteilung_filter = request.GET.get('abteilung')
    if abteilung_filter and request.user.is_staff:
        mitarbeiter_liste = mitarbeiter_liste.filter(abteilung=abteilung_filter)
    
    # Filter nach Standort
    standort_filter = request.GET.get('standort')
    if standort_filter:
        mitarbeiter_liste = mitarbeiter_liste.filter(standort=standort_filter)

    context = {
        'mitarbeiter_liste': mitarbeiter_liste,
        'mitarbeiter': mitarbeiter_liste,  # ← Für Kompatibilität hinzufügen
        'abteilung_filter': abteilung_filter,
        'standort_filter': standort_filter,
        'anzahl_siegburg': mitarbeiter_liste.filter(standort='siegburg').count(),  # ← NEU
        'anzahl_bonn': mitarbeiter_liste.filter(standort='bonn').count(),  # ← NEU
    }
        
    return render(request, 'arbeitszeit/mitarbeiter_uebersicht.html', context)

from django.contrib.auth import login
from django.contrib.auth.models import User
from .forms import RegisterForm



def register(request):
    """Registrierungsansicht für neue Benutzer"""
    if request.user.is_authenticated:
        return redirect('arbeitszeit:dashboard')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            try:
                # Benutzer erstellen
                user = User.objects.create_user(
                    username=form.cleaned_data['username'],
                    email=form.cleaned_data['email'],
                    password=form.cleaned_data['password1'],
                    first_name=form.cleaned_data['vorname'],
                    last_name=form.cleaned_data['nachname'],
                )

                # Mitarbeiter erstellen
                Mitarbeiter.objects.create(
                    user=user,
                    personalnummer=form.cleaned_data['personalnummer'],
                    vorname=form.cleaned_data['vorname'],
                    nachname=form.cleaned_data['nachname'],
                    abteilung=form.cleaned_data['abteilung'],
                    standort=form.cleaned_data['standort'],
                    eintrittsdatum=form.cleaned_data['eintrittsdatum'],
                    aktiv=True
                )

                # Automatisch einloggen
                login(request, user)
                messages.success(request, 'Registrierung erfolgreich! Willkommen!')
                return redirect('arbeitszeit:dashboard')
                
            except Exception as e:
                messages.error(request, f'Ein Fehler ist aufgetreten: {str(e)}')
        else:
            messages.error(request, 'Bitte korrigieren Sie die Fehler im Formular.')
    else:
        form = RegisterForm()

    return render(request, 'arbeitszeit/register.html', {'form': form})
@login_required
def admin_vereinbarung_loeschen(request, pk):
    """Vereinbarung löschen (nur für Vorgesetzte)"""
    if not request.user.is_staff:
        messages.error(request, "Sie haben keine Berechtigung für diese Aktion.")
        return redirect('arbeitszeit:dashboard')
    
    vereinbarung = get_object_or_404(Arbeitszeitvereinbarung, pk=pk)
    
    if request.method == 'POST':
        mitarbeiter_name = vereinbarung.mitarbeiter.vollname
        antragsart = vereinbarung.get_antragsart_display()
        
        # Lösche die Vereinbarung
        vereinbarung.delete()
        
        messages.success(
            request, 
            f'Vereinbarung von {mitarbeiter_name} ({antragsart}) wurde erfolgreich gelöscht.'
        )
        
        return redirect('arbeitszeit:admin_vereinbarungen')
    
    # Falls GET-Request, redirect zur Übersicht
    return redirect('arbeitszeit:admin_vereinbarungen')


@login_required
def admin_vereinbarung_docx_export(request, pk):
    """Generiert ein DOCX-Dokument für eine Arbeitszeitvereinbarung - NUR Python"""
    from django.http import HttpResponse
    from django.db.models import Case, When, IntegerField
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import io
    
    if not request.user.is_staff:
        messages.error(request, "Sie haben keine Berechtigung für diese Aktion.")
        return redirect('arbeitszeit:dashboard')
    
    vereinbarung = get_object_or_404(Arbeitszeitvereinbarung, pk=pk)
    
    # Tagesarbeitszeiten mit korrekter Sortierung
    tagesarbeitszeiten = vereinbarung.tagesarbeitszeiten.annotate(
        sort_order=Case(
            When(wochentag='montag', then=1),
            When(wochentag='dienstag', then=2),
            When(wochentag='mittwoch', then=3),
            When(wochentag='donnerstag', then=4),
            When(wochentag='freitag', then=5),
            When(wochentag='samstag', then=6),
            When(wochentag='sonntag', then=7),
            default=99,
            output_field=IntegerField(),
        )
    ).order_by('sort_order')
    
    # Dokument erstellen
    doc = Document()
    
    # Seitenränder (A4, 1 Zoll Ränder)
    sections = doc.sections
    for section in sections:
        section.page_height = Inches(11.69)  # A4 Höhe
        section.page_width = Inches(8.27)    # A4 Breite
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)
    
    # Standard-Schriftart
    style = doc.styles['Normal']
    font = style.font
    font.name = 'Arial'
    font.size = Pt(12)
    
    # Leerzeilen für Anschrift (3-4 Zeilen)
    for i in range(4):
        doc.add_paragraph()
    
    # Betreff (fett)
    betreff_text = 'Flexible Arbeitszeit'
    if vereinbarung.antragsart == 'weiterbewilligung':
        betreff_text += ' - Weiterbewilligung'
    elif vereinbarung.antragsart == 'verringerung':
        betreff_text += ' - Verringerung'
    elif vereinbarung.antragsart == 'erhoehung':
        betreff_text += ' - Erhöhung'
    elif vereinbarung.antragsart == 'beendigung':
        betreff_text += ' - Beendigung'
    
    p = doc.add_paragraph()
    run = p.add_run(f'Betreff: {betreff_text}')
    run.bold = True
    run.font.size = Pt(12)
    
    doc.add_paragraph()  # Leerzeile
    
    # Antragsart (größer und fett)
    p = doc.add_paragraph()
    run = p.add_run(vereinbarung.get_antragsart_display())
    run.bold = True
    run.font.size = Pt(14)
    
    # Wochensumme
    if vereinbarung.wochenstunden:
        wochensumme_text = f'{vereinbarung.wochenstunden} Stunden pro Woche'
    else:
        wochensumme_text = 'Individuelle Wochenverteilung'

    doc.add_paragraph(wochensumme_text)

        
    # Gültigkeit
    gueltig_bis = vereinbarung.gueltig_bis.strftime('%d.%m.%Y') if vereinbarung.gueltig_bis else 'unbefristet'
    doc.add_paragraph(f'Gültig: {vereinbarung.gueltig_ab.strftime("%d.%m.%Y")} bis {gueltig_bis}')
    
    doc.add_paragraph()  # Leerzeile
    
    # Anrede
    doc.add_paragraph('Sehr geehrte Damen und Herren,')
    doc.add_paragraph()
    
    # Einleitungstext
    doc.add_paragraph('hiermit wird die folgende Arbeitszeitvereinbarung getroffen:')
    doc.add_paragraph()
    
    # Wenn Tagesarbeitszeiten vorhanden, Tabelle erstellen
    if tagesarbeitszeiten.exists():
        # Überschrift
        p = doc.add_paragraph()
        run = p.add_run('Wochenverteilung:')
        run.bold = True
        
        # Tabelle erstellen
        table = doc.add_table(rows=1, cols=2)
        table.style = 'Light Grid Accent 1'
        
        # Header-Zeile
        hdr_cells = table.rows[0].cells
        hdr_cells[0].text = 'Wochentag'
        hdr_cells[1].text = 'Arbeitszeit'
        
        # Header formatieren (grün, weiß, fett)
        for cell in hdr_cells:
            # Hintergrundfarbe grün
            shading_elm = OxmlElement('w:shd')
            shading_elm.set(qn('w:fill'), '1a4d2e')
            cell._element.get_or_add_tcPr().append(shading_elm)
            
            # Text weiß und fett
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.font.color.rgb = RGBColor(255, 255, 255)
                    run.bold = True
        
        # Rechtsbündig für "Arbeitszeit"
        hdr_cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        
        # Daten-Zeilen
        for tag in tagesarbeitszeiten:
            row_cells = table.add_row().cells
            row_cells[0].text = tag.get_wochentag_display()
            row_cells[1].text = tag.formatierte_zeit
            row_cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        
        # Summen-Zeile (falls vorhanden)
        if hasattr(vereinbarung, 'get_wochenstunden_summe') and vereinbarung.get_wochenstunden_summe:
            row_cells = table.add_row().cells
            row_cells[0].text = 'Summe pro Woche'
            row_cells[1].text = vereinbarung.get_wochenstunden_summe
            
            # Formatierung: fett und hellgrüner Hintergrund
            for cell in row_cells:
                shading_elm = OxmlElement('w:shd')
                shading_elm.set(qn('w:fill'), 'E8F5E9')
                cell._element.get_or_add_tcPr().append(shading_elm)
                
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
            
            row_cells[1].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
        
        doc.add_paragraph()  # Leerzeile nach Tabelle
    
    # Gültigkeitstext
    doc.add_paragraph(f'Diese Vereinbarung gilt vom {vereinbarung.gueltig_ab.strftime("%d.%m.%Y")} bis {gueltig_bis}.')
    doc.add_paragraph()
    
    # Grußformel
    doc.add_paragraph()
    doc.add_paragraph('Mit freundlichen Grüßen')
    doc.add_paragraph()
    doc.add_paragraph()
    doc.add_paragraph()
    
    # Unterschriftenfeld
    p = doc.add_paragraph('_______________________________')
    p = doc.add_paragraph('Unterschrift')
    
    # Dokument in Memory speichern
    file_stream = io.BytesIO()
    doc.save(file_stream)
    file_stream.seek(0)
    
    # Als Download zurückgeben
    response = HttpResponse(
        file_stream.read(),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    filename = f"Arbeitszeitvereinbarung_{vereinbarung.mitarbeiter.nachname}_{vereinbarung.pk}.docx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response
@login_required
def admin_vereinbarung_pdf_export(request, pk):
    """Generiert ein PDF-Dokument mit allen Stammdaten"""
    from django.http import HttpResponse
    from django.db.models import Case, When, IntegerField
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import io
    from datetime import datetime
    
    if not request.user.is_staff:
        messages.error(request, "Sie haben keine Berechtigung für diese Aktion.")
        return redirect('arbeitszeit:dashboard')
    
    vereinbarung = get_object_or_404(Arbeitszeitvereinbarung, pk=pk)
    
    # Tagesarbeitszeiten mit korrekter Sortierung
    tagesarbeitszeiten = vereinbarung.tagesarbeitszeiten.annotate(
        sort_order=Case(
            When(wochentag='montag', then=1),
            When(wochentag='dienstag', then=2),
            When(wochentag='mittwoch', then=3),
            When(wochentag='donnerstag', then=4),
            When(wochentag='freitag', then=5),
            When(wochentag='samstag', then=6),
            When(wochentag='sonntag', then=7),
            default=99,
            output_field=IntegerField(),
        )
    ).order_by('sort_order')
    
    # PDF in Memory erstellen
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#1a4d2e'),
        spaceAfter=20,
        alignment=TA_CENTER
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#1a4d2e'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    normal_style = styles['Normal']
    
    # Story (Inhalt)
    story = []
    
    # Titel
    story.append(Paragraph('Arbeitszeitvereinbarung', title_style))
    story.append(Spacer(1, 0.5*cm))
    
    # Betreff
    betreff_text = 'Flexible Arbeitszeit'
    if vereinbarung.antragsart == 'weiterbewilligung':
        betreff_text += ' - Weiterbewilligung'
    elif vereinbarung.antragsart == 'verringerung':
        betreff_text += ' - Verringerung'
    elif vereinbarung.antragsart == 'erhoehung':
        betreff_text += ' - Erhöhung'
    elif vereinbarung.antragsart == 'beendigung':
        betreff_text += ' - Beendigung'
    
    story.append(Paragraph(f'<b>Betreff:</b> {betreff_text}', normal_style))
    story.append(Spacer(1, 0.5*cm))
    
    # Stammdaten Tabelle
    story.append(Paragraph('Stammdaten', heading_style))
    
    stammdaten_data = [
        ['Personalnummer:', vereinbarung.mitarbeiter.personalnummer],
        ['Name:', vereinbarung.mitarbeiter.nachname],
        ['Vorname:', vereinbarung.mitarbeiter.vorname],
        ['Vollständiger Name:', vereinbarung.mitarbeiter.vollname],
        ['Abteilung:', vereinbarung.mitarbeiter.abteilung],
        ['Standort:', vereinbarung.mitarbeiter.get_standort_display()],
        ['Eintrittsdatum:', vereinbarung.mitarbeiter.eintrittsdatum.strftime('%d.%m.%Y')],
    ]
    
    stammdaten_table = Table(stammdaten_data, colWidths=[5*cm, 10*cm])
    stammdaten_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E8F5E9')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1a4d2e')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    
    story.append(stammdaten_table)
    story.append(Spacer(1, 0.7*cm))
    
    # Vereinbarungsdetails
    story.append(Paragraph('Vereinbarungsdetails', heading_style))
    
    vereinbarung_data = [
        ['Antragsart:', vereinbarung.get_antragsart_display()],
        ['Status:', vereinbarung.get_status_display()],
        ['Beantragt am:', vereinbarung.created_at.strftime('%d.%m.%Y %H:%M') + ' Uhr'],
    ]
    
    if vereinbarung.arbeitszeit_typ:
        vereinbarung_data.append(['Arbeitszeit-Typ:', vereinbarung.get_arbeitszeit_typ_display()])
    
    vereinbarung_data.extend([
        ['Gültig ab:', vereinbarung.gueltig_ab.strftime('%d.%m.%Y')],
        ['Gültig bis:', vereinbarung.gueltig_bis.strftime('%d.%m.%Y') if vereinbarung.gueltig_bis else 'unbefristet'],
        ['Telearbeit:', 'Ja' if vereinbarung.telearbeit else 'Nein'],
    ])
    
    if vereinbarung.genehmigt_von:
        vereinbarung_data.extend([
            ['Genehmigt von:', vereinbarung.genehmigt_von.get_full_name()],
            ['Genehmigt am:', vereinbarung.genehmigt_am.strftime('%d.%m.%Y %H:%M') + ' Uhr'],
        ])
    
    vereinbarung_table = Table(vereinbarung_data, colWidths=[5*cm, 10*cm])
    vereinbarung_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E8F5E9')),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#1a4d2e')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    
    story.append(vereinbarung_table)
    story.append(Spacer(1, 0.7*cm))
    
    # Arbeitszeit-Details
    if vereinbarung.wochenstunden:
        story.append(Paragraph('Arbeitszeit', heading_style))
        story.append(Paragraph(
            f'<b>{vereinbarung.wochenstunden} Stunden pro Woche</b>',
            normal_style
        ))
        story.append(Spacer(1, 0.5*cm))
    
    # Wochenverteilung (falls vorhanden)
    if tagesarbeitszeiten.exists():
        story.append(Paragraph('Wochenverteilung', heading_style))
        
        # Tabelle für Wochenverteilung
        wochen_data = [['Wochentag', 'Arbeitszeit']]
        
        for tag in tagesarbeitszeiten:
            wochen_data.append([
                tag.get_wochentag_display(),
                tag.formatierte_zeit
            ])
        
        # Summe berechnen
        if hasattr(vereinbarung, 'get_wochenstunden_summe') and vereinbarung.get_wochenstunden_summe:
            wochen_data.append(['Summe pro Woche', vereinbarung.get_wochenstunden_summe])
        
        wochen_table = Table(wochen_data, colWidths=[7.5*cm, 7.5*cm])
        wochen_table.setStyle(TableStyle([
            # Header
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a4d2e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
            ('TOPPADDING', (0, 0), (-1, 0), 10),
            
            # Daten-Zeilen
            ('ALIGN', (0, 1), (0, -2), 'LEFT'),
            ('ALIGN', (1, 1), (1, -2), 'RIGHT'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            
            # Summen-Zeile (letzte Zeile)
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E8F5E9')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('ALIGN', (1, -1), (1, -1), 'RIGHT'),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        
        story.append(wochen_table)
        story.append(Spacer(1, 0.7*cm))
    
    # Gültigkeitstext
    gueltig_bis_text = vereinbarung.gueltig_bis.strftime('%d.%m.%Y') if vereinbarung.gueltig_bis else 'unbefristet'
    story.append(Paragraph(
        f'Diese Vereinbarung gilt vom {vereinbarung.gueltig_ab.strftime("%d.%m.%Y")} bis {gueltig_bis_text}.',
        normal_style
    ))
    story.append(Spacer(1, 1*cm))
    
    # Bemerkungen (falls vorhanden)
    if vereinbarung.bemerkungen:
        story.append(Paragraph('Bemerkungen', heading_style))
        story.append(Paragraph(vereinbarung.bemerkungen, normal_style))
        story.append(Spacer(1, 0.5*cm))
    
    # Grußformel und Unterschrift
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph('Mit freundlichen Grüßen', normal_style))
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph('_______________________________', normal_style))
    story.append(Paragraph('Unterschrift', normal_style))
    
    # Footer mit Erstellungsdatum
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph(
        f'<i>Erstellt am: {datetime.now().strftime("%d.%m.%Y um %H:%M Uhr")}</i>',
        ParagraphStyle('Footer', parent=normal_style, fontSize=8, textColor=colors.grey)
    ))
    
    # PDF erstellen
    doc.build(story)
    
    # PDF als Download zurückgeben
    buffer.seek(0)
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    filename = f"Arbeitszeitvereinbarung_{vereinbarung.mitarbeiter.nachname}_{vereinbarung.pk}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response
@login_required
def mitarbeiter_detail(request, pk):
    """Detail/Bearbeiten eines Mitarbeiters"""
    mitarbeiter = get_object_or_404(Mitarbeiter, pk=pk)
    
    # Berechtigung prüfen
    if not (request.user.is_staff or 
            (hasattr(request.user, 'mitarbeiter') and 
             request.user.mitarbeiter.rolle == 'schichtplaner')):
        messages.error(request, "Keine Berechtigung.")
        return redirect('arbeitszeit:dashboard')
    
    if request.method == 'POST':
        # Basis
        mitarbeiter.schichtplan_kennung = request.POST.get('schichtplan_kennung', '')
        mitarbeiter.kann_tagschicht = 'kann_tagschicht' in request.POST
        mitarbeiter.kann_nachtschicht = 'kann_nachtschicht' in request.POST
        
        # NEU: Wochenenden
        try:
            mitarbeiter.max_wochenenden_pro_monat = int(request.POST.get('max_wochenenden_pro_monat', 4))
        except ValueError:
            mitarbeiter.max_wochenenden_pro_monat = 4
        
        # NEU: Spezielle Regeln
        mitarbeiter.nachtschicht_nur_wochenende = 'nachtschicht_nur_wochenende' in request.POST
        mitarbeiter.nur_zusatzdienste_wochentags = 'nur_zusatzdienste_wochentags' in request.POST
        
        # NEU: Verfügbarkeit
        mitarbeiter.verfuegbarkeit = request.POST.get('verfuegbarkeit', 'voll')
        
        # NEU: Freitext
        mitarbeiter.schichtplan_einschraenkungen = request.POST.get('schichtplan_einschraenkungen', '')
        
        mitarbeiter.save()
        
        messages.success(request, f"✅ {mitarbeiter.vollname} aktualisiert!")
        return redirect('schichtplan:mitarbeiter_uebersicht')
    
    return render(request, 'arbeitszeit/mitarbeiter_detail.html', {
        'mitarbeiter': mitarbeiter
    })
