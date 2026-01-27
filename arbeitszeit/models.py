"""
Django Models für Arbeitszeitverwaltung
"""
from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError

class Mitarbeiter(models.Model):
    

    # === CHOICES ZUERST ===
    STANDORT_CHOICES = [
        ('siegburg', 'Siegburg'),
        ('bonn', 'Bonn'),
    ]

    ROLLE_CHOICES = [
    ('mitarbeiter', 'Mitarbeiter'),
    ('sachbearbeiter', 'Sachbearbeiter'),
    ('schichtplaner', 'Schichtplaner'),  
    ]

    ARBEITSZEIT_TYP_CHOICES = [
        ('typ_a', 'Typ A - 7:48h'),
        ('typ_b', 'Typ B - 8:12h'),
        ('typ_c', 'Typ C - 8:00h'),
        ('individuell', 'Individuell'),
    ]

    VERFUEGBARKEIT_CHOICES = [
        ('voll', 'Vollzeit - alle Schichten'),
        ('teilzeit', 'Teilzeit - begrenzte Schichten'),
        ('dauerkrank', 'Dauerkrank - nicht einplanbar'),
        ('nur_wochenende', 'Nur Wochenende (Fr/Sa/So)'),
        ('keine_wochenende', 'Keine Wochenenden'),
    ]

    PRIORITAET_CHOICES = [
        ('niedrig', 'Niedrig - Flexibel einsetzbar'),
        ('normal', 'Normal'),
        ('hoch', 'Hoch - Präferenzen bevorzugt berücksichtigen'),
    ]
   
    # === BASISDATEN ===
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    personalnummer = models.CharField(max_length=20, unique=True)
    vorname = models.CharField(max_length=100)
    nachname = models.CharField(max_length=100)
    abteilung = models.CharField(max_length=100)

    standort = models.CharField(
        max_length=20,
        choices=STANDORT_CHOICES
    )

    rolle = models.CharField(
        max_length=20,
        choices=ROLLE_CHOICES,
        default='mitarbeiter'
    )
    eintrittsdatum = models.DateField(null=True, blank=True)
    aktiv = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # === SCHICHTPLAN-PRÄFERENZEN ===
    
    # Zuordnung für Excel-Import
    schichtplan_kennung = models.CharField(
        max_length=10,
        blank=True,
        default='',
        help_text="z.B. 'MA1', 'MA2' für Excel-Import"
    )
    
    kann_tagschicht = models.BooleanField(
        default=True,
        verbose_name="Kann Tagschichten arbeiten"
    )
    
    kann_nachtschicht = models.BooleanField(
        default=True,
        verbose_name="Kann Nachtschichten arbeiten"
    )
    
    # NEU: Wochenend-Einschränkungen
    max_wochenenden_pro_monat = models.IntegerField(
        default=4,
        verbose_name="Max. Wochenenden pro Monat",
        help_text="0 = keine Wochenenden, 4 = alle möglich"
    )
    
    # NEU: Nachtschicht nur am Wochenende
    nachtschicht_nur_wochenende = models.BooleanField(
        default=False,
        verbose_name="Nachtschicht nur Fr/Sa/So",
        help_text="Wenn aktiv: Nachtschichten nur Freitag, Samstag, Sonntag"
    )
    
    # NEU: Nur Zusatzdienste in der Woche
    nur_zusatzdienste_wochentags = models.BooleanField(
        default=False,
        verbose_name="In der Woche nur Zusatzdienste (Z)",
        help_text="Mo-Do nur Zusatzarbeiten, keine regulären Schichten"
    )
    
    # NEU: Freitext für spezielle Wünsche
    schichtplan_einschraenkungen = models.TextField(
        blank=True,
        verbose_name="Weitere Einschränkungen / Besonderheiten",
        help_text="Freitext für spezielle Wünsche, medizinische Gründe, etc."
    )
    
    # Optional: Verfügbarkeit (für später)
    VERFUEGBARKEIT_CHOICES = [
        ('voll', 'Vollzeit - alle Schichten'),
        ('teilzeit', 'Teilzeit - begrenzte Schichten'),
        ('wochenende_only', 'Nur Wochenende (Fr/Sa/So)'),
        ('wochentags_only', 'Nur Wochentags (Mo-Do)'),
        ('dauerkrank', 'Dauerkrank - nicht einplanbar'),
    ]
    
    verfuegbarkeit = models.CharField(
        max_length=20,
        choices=VERFUEGBARKEIT_CHOICES,
        default='voll',
        blank=True,
        verbose_name="Verfügbarkeit"
    )
    
   
    arbeitszeit_typ = models.CharField(
        max_length=20,
        choices=ARBEITSZEIT_TYP_CHOICES,
        default='typ_c',
        blank=True
    )
    
    # Schichtfähigkeiten
    kann_tagschicht = models.BooleanField(default=True)
    kann_nachtschicht = models.BooleanField(default=True)
    nur_zusatzarbeiten = models.BooleanField(
        default=False,
        help_text="Nur für Zusatzarbeiten verfügbar (12h)"
    )
    
    # Wochenend-Einschränkungen
    max_wochenenden_pro_monat = models.IntegerField(
        default=4,
        help_text="Maximal X Wochenenden pro Monat"
    )
    
    
    verfuegbarkeit = models.CharField(
        max_length=20,
        choices=VERFUEGBARKEIT_CHOICES,
        default='voll'
    )
    
    # Nachtschicht-Einschränkungen
    nachtschicht_nur_wochenende = models.BooleanField(
        default=False,
        help_text="Nachtschichten nur Fr/Sa/So"
    )
    
    # Maximale Schichten
    max_schichten_pro_monat = models.IntegerField(
        null=True,
        blank=True,
        help_text="Begrenzt für Teilzeit"
    )
    
    max_aufeinanderfolgende_tage = models.IntegerField(
        default=5,
        help_text="Max. Arbeitstage in Folge"
    )
    
    # Bemerkungen für Planer
    schichtplan_bemerkungen = models.TextField(
        blank=True,
        help_text="Besondere Hinweise für Schichtplaner"
    )
    
    
    planungs_prioritaet = models.CharField(
        max_length=10,
        choices=PRIORITAET_CHOICES,
        default='normal',
        blank=True
    )
    
    class Meta:
        verbose_name = "Mitarbeiter"
        verbose_name_plural = "Mitarbeiter"
        ordering = ['nachname', 'vorname']
    
    def __str__(self):
        return f"{self.nachname}, {self.vorname} ({self.personalnummer})"
    
    @property
    def vollname(self):
        return f"{self.vorname} {self.nachname}"
    
    
    def get_aktuelle_vereinbarung(self):
        """Gibt die aktuell gültige Vereinbarung zurück"""
        from django.utils import timezone
        heute = timezone.now().date()
        
        return self.arbeitszeitvereinbarungen.filter(
            status='aktiv',
            gueltig_ab__lte=heute
        ).filter(
            Q(gueltig_bis__isnull=True) | Q(gueltig_bis__gte=heute)
        ).first()


class Arbeitszeitvereinbarung(models.Model):
    """Arbeitszeitvereinbarung für einen Mitarbeiter"""
    mitarbeiter = models.ForeignKey(
        Mitarbeiter, 
        on_delete=models.CASCADE, 
        related_name='arbeitszeitvereinbarungen'
    )
    
    ANTRAGSART_CHOICES = [
    ('weiterbewilligung', 'Weiterbewilligung'),
    ('verringerung', 'Verringerung'),
    ('erhoehung', 'Erhöhung'),
    ('beendigung', 'Beendigung'),  # NEU!
]
    antragsart = models.CharField(max_length=20, choices=ANTRAGSART_CHOICES)
    
    TYPE_CHOICES = [
        ('regelmaessig', 'Regelmäßig'),
        ('individuell', 'Individuelle Wochenverteilung'),
    ]
    arbeitszeit_typ = models.CharField(max_length=20, choices=TYPE_CHOICES)
    
    # Für regelmäßige Arbeitszeit
    wochenstunden = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        null=True, 
        blank=True,
        validators=[MinValueValidator(2), MaxValueValidator(48)]
    )
    
    # Datum
    gueltig_ab = models.DateField()
    gueltig_bis = models.DateField(null=True, blank=True)
    
    # Telearbeit
    telearbeit = models.BooleanField(default=False)
    
    # Status
    STATUS_CHOICES = [
        ('entwurf', 'Entwurf'),
        ('beantragt', 'Beantragt'),
        ('genehmigt', 'Genehmigt'),
        ('abgelehnt', 'Abgelehnt'),
        ('aktiv', 'Aktiv'),
        ('beendet', 'Beendet'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='entwurf')
    
    # Genehmigung
    genehmigt_von = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='genehmigte_vereinbarungen'
    )
    genehmigt_am = models.DateTimeField(null=True, blank=True)
    
    # Beendigung
    beendigung_beantragt = models.BooleanField(default=False)
    beendigung_datum = models.DateField(null=True, blank=True)
    
    # Notizen
    bemerkungen = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Arbeitszeitvereinbarung"
        verbose_name_plural = "Arbeitszeitvereinbarungen"
        ordering = ['-gueltig_ab']
    
    def __str__(self):
        return f"{self.mitarbeiter.vollname} - {self.get_antragsart_display()} ({self.gueltig_ab})"
    
    @property
    def get_wochenstunden_summe(self):
    
    # Regelmäßige Arbeitszeit
        if self.arbeitszeit_typ == 'regelmaessig' and self.wochenstunden:
            stunden = int(self.wochenstunden)
            minuten = int((self.wochenstunden - stunden) * 60)
            return f"{stunden}:{minuten:02d}h"

    # Individuelle Verteilung
        if self.arbeitszeit_typ == 'individuell':
            tage = self.tagesarbeitszeiten.all()
            if not tage.exists():
                return None

            total_minuten = sum(
                (t.stunden * 60 + t.minuten) for t in tage
            )
            stunden = total_minuten // 60
            minuten = total_minuten % 60
            return f"{stunden}:{minuten:02d}h"

        return None
    
    @property
    def ist_aktiv(self):
        """Prüft, ob die Vereinbarung aktuell aktiv ist"""
        heute = timezone.now().date()
        if self.status != 'aktiv':
            return False
        if self.gueltig_ab > heute:
            return False
        if self.gueltig_bis and self.gueltig_bis < heute:
            return False
        return True
    
    @property
    def tagesarbeitszeit(self):
        """Berechnet die durchschnittliche Tagesarbeitszeit (nur für regelmäßig)"""
        if self.arbeitszeit_typ == 'regelmaessig' and self.wochenstunden:
            tageszeit = float(self.wochenstunden) / 5
            stunden = int(tageszeit)
            minuten = int((tageszeit - stunden) * 60)
            return f"{stunden}:{minuten:02d}h"
        return None
    


class Tagesarbeitszeit(models.Model):
    """Individuelle Arbeitszeit pro Wochentag"""
    vereinbarung = models.ForeignKey(
        Arbeitszeitvereinbarung,
        on_delete=models.CASCADE,
        related_name='tagesarbeitszeiten'
    )
    
    WOCHENTAG_CHOICES = [
        ('montag', 'Montag'),
        ('dienstag', 'Dienstag'),
        ('mittwoch', 'Mittwoch'),
        ('donnerstag', 'Donnerstag'),
        ('freitag', 'Freitag'),
        ('samstag', 'Samstag'),
        ('sonntag', 'Sonntag'),
    ]
    wochentag = models.CharField(max_length=15, choices=WOCHENTAG_CHOICES)
    
    # Zeitwert im Format HMM (z.B. 830 für 8:30)
    zeitwert = models.IntegerField(
        validators=[MinValueValidator(200), MaxValueValidator(1200)]
    )
    
    class Meta:
        verbose_name = "Tagesarbeitszeit"
        verbose_name_plural = "Tagesarbeitszeiten"
        ordering = ['wochentag']
        unique_together = ['vereinbarung', 'wochentag']
    
    def __str__(self):
        return f"{self.get_wochentag_display()}: {self.stunden}:{self.minuten:02d}h"
    
    @property
    def stunden(self):
        """Extrahiert Stunden aus Zeitwert"""
        return self.zeitwert // 100
    
    @property
    def minuten(self):
        """Extrahiert Minuten aus Zeitwert"""
        return self.zeitwert % 100
    
    @property
    def formatierte_zeit(self):
        """Gibt formatierte Zeit zurück"""
        return f"{self.stunden}:{self.minuten:02d}h"


class ArbeitszeitHistorie(models.Model):
    """Historie aller Änderungen an Arbeitszeitvereinbarungen"""
    vereinbarung = models.ForeignKey(
        Arbeitszeitvereinbarung,
        on_delete=models.CASCADE,
        related_name='historie'
    )
    
    aenderung_durch = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    aenderung_am = models.DateTimeField(auto_now_add=True)
    
    ALTER_STATUS_CHOICES = Arbeitszeitvereinbarung.STATUS_CHOICES
    alter_status = models.CharField(max_length=20, choices=ALTER_STATUS_CHOICES)
    neuer_status = models.CharField(max_length=20, choices=ALTER_STATUS_CHOICES)
    
    bemerkung = models.TextField(blank=True)
    
    class Meta:
        verbose_name = "Arbeitszeithistorie"
        verbose_name_plural = "Arbeitszeithistorien"
        ordering = ['-aenderung_am']
    
    def __str__(self):
        return f"{self.vereinbarung.mitarbeiter.vollname} - {self.alter_status} → {self.neuer_status}"


class Urlaubsanspruch(models.Model):
    """Urlaubsanspruch basierend auf Arbeitszeit"""
    mitarbeiter = models.ForeignKey(
        Mitarbeiter,
        on_delete=models.CASCADE,
        related_name='urlaubsansprueche'
    )
    
    jahr = models.IntegerField()
    
    # Urlaubstage basierend auf Vollzeit (z.B. 30 Tage)
    jahresurlaubstage_vollzeit = models.DecimalField(max_digits=5, decimal_places=2)
    
    # Tatsächlicher Anspruch basierend auf Arbeitszeit
    jahresurlaubstage_anteilig = models.DecimalField(max_digits=5, decimal_places=2)
    
    # Verbrauch
    genommene_urlaubstage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    class Meta:
        verbose_name = "Urlaubsanspruch"
        verbose_name_plural = "Urlaubsansprüche"
        unique_together = ['mitarbeiter', 'jahr']
        ordering = ['-jahr']
    
    def __str__(self):
        return f"{self.mitarbeiter.vollname} - {self.jahr}"
    
    @property
    def resturlaubstage(self):
        """Berechnet verbleibende Urlaubstage"""
        return self.jahresurlaubstage_anteilig - self.genommene_urlaubstage


class Zeiterfassung(models.Model):
    """Tägliche Zeiterfassung"""
    mitarbeiter = models.ForeignKey(
        Mitarbeiter,
        on_delete=models.CASCADE,
        related_name='zeiterfassungen'
    )
    
    datum = models.DateField()
    
    # Arbeitszeit
    arbeitsbeginn = models.TimeField(null=True, blank=True)
    arbeitsende = models.TimeField(null=True, blank=True)
    pause_minuten = models.IntegerField(default=0)
    
    # Berechnete Arbeitszeit
    arbeitszeit_minuten = models.IntegerField(null=True, blank=True)
    
    # Art
    ART_CHOICES = [
        ('buero', 'Büro'),
        ('homeoffice', 'Homeoffice/Telearbeit'),
        ('urlaub', 'Urlaub'),
        ('krank', 'Krank'),
        ('sonderurlaub', 'Sonderurlaub'),
    ]
    art = models.CharField(max_length=20, choices=ART_CHOICES, default='buero')
    
    bemerkung = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Zeiterfassung"
        verbose_name_plural = "Zeiterfassungen"
        unique_together = ['mitarbeiter', 'datum']
        ordering = ['-datum']
    
    def __str__(self):
        return f"{self.mitarbeiter.vollname} - {self.datum}"
    
    def save(self, *args, **kwargs):
        """Berechnet automatisch die Arbeitszeit"""
        if self.arbeitsbeginn and self.arbeitsende:
            from datetime import datetime, timedelta
            beginn = datetime.combine(self.datum, self.arbeitsbeginn)
            ende = datetime.combine(self.datum, self.arbeitsende)
            
            if ende < beginn:
                ende += timedelta(days=1)
            
            differenz = ende - beginn
            self.arbeitszeit_minuten = int(differenz.total_seconds() / 60) - self.pause_minuten
        
        super().save(*args, **kwargs)
    
    @property
    def arbeitszeit_formatiert(self):
        """Gibt Arbeitszeit formatiert zurück"""
        if self.arbeitszeit_minuten:
            stunden = self.arbeitszeit_minuten // 60
            minuten = self.arbeitszeit_minuten % 60
            return f"{stunden}:{minuten:02d}h"
        return "0:00h"
    def clean(self):
        stunden = self.zeitwert // 100
        minuten = self.zeitwert % 100

        if minuten >= 60:
            raise ValidationError("Minuten dürfen nicht ≥ 60 sein")

        if stunden < 0 or stunden > 24:
            raise ValidationError("Ungültige Stundenzahl")