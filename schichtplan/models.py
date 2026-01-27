from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta


# ============================================
# 1. SCHICHTTYP (braucht nichts)
# ============================================

class Schichttyp(models.Model):
    """Definition eines Schichttyps (Tag, Nacht, etc.)"""
    name = models.CharField(max_length=100)
    kuerzel = models.CharField(max_length=10)
    start_zeit = models.TimeField()
    ende_zeit = models.TimeField()
    farbe = models.CharField(max_length=7, default='#6c757d')
    pausenzeit_minuten = models.IntegerField(default=0)
    aktiv = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = "Schichttyp"
        verbose_name_plural = "Schichttypen"
        ordering = ['start_zeit']
    
    def __str__(self):
        return f"{self.name} ({self.kuerzel})"
    
    @property
    def arbeitszeit_stunden(self):
        """Berechnet Arbeitsstunden"""
        from datetime import datetime, timedelta
        start = datetime.combine(datetime.today(), self.start_zeit)
        ende = datetime.combine(datetime.today(), self.ende_zeit)
        if ende < start:
            ende += timedelta(days=1)
        dauer = (ende - start).total_seconds() / 3600
        dauer -= self.pausenzeit_minuten / 60
        return round(dauer, 2)


# ============================================
# 2. SCHICHTPLAN (braucht nur User)
# ============================================

class Schichtplan(models.Model):
    """Ein Schichtplan für einen bestimmten Zeitraum"""
    name = models.CharField(max_length=200)
    start_datum = models.DateField()
    ende_datum = models.DateField()
    
    STATUS_CHOICES = [
        ('entwurf', 'Entwurf'),
        ('veroeffentlicht', 'Veröffentlicht'),
        ('archiviert', 'Archiviert'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='entwurf')
    
    erstellt_von = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    bemerkungen = models.TextField(blank=True)
    
    class Meta:
        verbose_name = "Schichtplan"
        verbose_name_plural = "Schichtpläne"
        ordering = ['-start_datum']
    
    def __str__(self):
        return f"{self.name} ({self.start_datum} - {self.ende_datum})"
    
    @property
    def anzahl_tage(self):
        """Anzahl Tage im Plan"""
        return (self.ende_datum - self.start_datum).days + 1
    
    @property
    def anzahl_schichten(self):
        """Anzahl zugewiesener Schichten"""
        return self.schichten.count()
    
    def clean(self):
        if self.ende_datum and self.start_datum and self.ende_datum < self.start_datum:
            raise ValidationError("Ende-Datum muss nach Start-Datum liegen.")


# ============================================
# 3. SCHICHTWUNSCHPERIODE (braucht nur User)
# ============================================

class SchichtwunschPeriode(models.Model):
    """
    Zeitraum für Wunscheingabe
    
    Definiert einen Zeitraum, in dem Mitarbeiter ihre Wünsche
    für einen bestimmten Monat eingeben können.
    """
    name = models.CharField(
        max_length=100,
        help_text="z.B. 'Wünsche für März 2026'"
    )
    
    fuer_monat = models.DateField(
        help_text="Für welchen Monat sind die Wünsche (z.B. 2026-03-01)"
    )
    
    eingabe_start = models.DateTimeField(
        help_text="Ab wann können Wünsche eingegeben werden"
    )
    
    eingabe_ende = models.DateTimeField(
        help_text="Bis wann können Wünsche eingegeben werden"
    )
    
    STATUS_CHOICES = [
        ('vorbereitung', 'In Vorbereitung'),
        ('offen', 'Offen - Wünsche können eingereicht werden'),
        ('geschlossen', 'Geschlossen - Wird geplant'),
        ('genehmigung', 'Wünsche werden genehmigt'),
        ('planung', 'Plan wird generiert'),
        ('veroeffentlicht', 'Plan ist veröffentlicht'),
    ]
    
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='vorbereitung'
    )
    
    erstellt_von = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='erstellte_wunschperioden'
    )
    
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Schichtwunsch-Periode"
        verbose_name_plural = "Schichtwunsch-Perioden"
        ordering = ['-fuer_monat']
    
    def __str__(self):
        return f"{self.name} ({self.fuer_monat.strftime('%B %Y')})"
    
    @property
    def ist_offen(self):
        """Können gerade Wünsche eingereicht werden?"""
        now = timezone.now()
        return self.status == 'offen' and self.eingabe_start <= now <= self.eingabe_ende
    
    @property
    def anzahl_wuensche(self):
        """Wie viele Wünsche wurden eingereicht?"""
        return self.schichtwunsch_set.count()
    
    @property
    def anzahl_genehmigungen_offen(self):
        """Wie viele Wünsche warten auf Genehmigung?"""
        return self.schichtwunsch_set.filter(
            benoetigt_genehmigung=True,
            genehmigt=False
        ).count()


# ============================================
# 4. SCHICHTWUNSCH (braucht SchichtwunschPeriode)
# ============================================

class Schichtwunsch(models.Model):
    """
    Mitarbeiter-Wünsche für einen Tag
    
    7 Kategorien:
    1. Urlaub
    2. Kein Tag, aber Nacht möglich
    3. Keine Nacht, aber Tag möglich
    4. Tag bevorzugt
    5. Nacht bevorzugt
    6. Gar nichts möglich
    7. Zusatzarbeit
    """
    
    WUNSCH_KATEGORIEN = [
        ('urlaub', '1 - Urlaub'),
        ('kein_tag_aber_nacht', '2 - Kein Tag, aber Nacht möglich'),
        ('keine_nacht_aber_tag', '3 - Keine Nacht, aber Tag möglich'),
        ('tag_bevorzugt', '4 - Tag bevorzugt'),
        ('nacht_bevorzugt', '5 - Nacht bevorzugt'),
        ('gar_nichts', '6 - Gar nichts möglich'),
        ('zusatzarbeit', '7 - Zusatzarbeit'),
    ]
    
    periode = models.ForeignKey(
        SchichtwunschPeriode,  # ← Jetzt definiert!
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Zu welcher Wunschperiode gehört dieser Wunsch"
    )
    
    mitarbeiter = models.ForeignKey(
        'arbeitszeit.Mitarbeiter',
        on_delete=models.CASCADE,
        related_name='schichtwuensche'
    )
    
    datum = models.DateField()
    
    wunsch = models.CharField(
        max_length=30,
        choices=WUNSCH_KATEGORIEN,
        help_text="Wunsch-Kategorie (1-7)"
    )
    
    begruendung = models.TextField(
        blank=True,
        help_text="Optional: Grund für Wunsch"
    )
    
    # Genehmigung
    benoetigt_genehmigung = models.BooleanField(default=False)
    genehmigt = models.BooleanField(default=False)
    genehmigt_von = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='genehmigte_wuensche'
    )
    genehmigt_am = models.DateTimeField(null=True, blank=True)
    
    erstellt_am = models.DateTimeField(auto_now_add=True)
    aktualisiert_am = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Schichtwunsch"
        verbose_name_plural = "Schichtwünsche"
        unique_together = [['mitarbeiter', 'datum']]
        ordering = ['datum', 'mitarbeiter']
    
    def __str__(self):
        return f"{self.mitarbeiter.vollname} - {self.datum} - {self.get_wunsch_display()}"
    
    def save(self, *args, **kwargs):
        # Urlaub und "gar nichts" benötigen Genehmigung
        if self.wunsch in ['urlaub', 'gar_nichts']:
            self.benoetigt_genehmigung = True
        else:
            self.benoetigt_genehmigung = False
        super().save(*args, **kwargs)
    
    @property
    def farbe(self):
        """Farbe für UI"""
        farben = {
            'urlaub': '#dc3545',
            'kein_tag_aber_nacht': '#0d6efd',
            'keine_nacht_aber_tag': '#ffc107',
            'tag_bevorzugt': '#198754',
            'nacht_bevorzugt': '#6f42c1',
            'gar_nichts': '#212529',
            'zusatzarbeit': '#fd7e14',
        }
        return farben.get(self.wunsch, '#6c757d')
    
    @property
    def prioritaet_stufe(self):
        """Numerische Priorität für Optimizer"""
        prioritaeten = {
            'urlaub': 100,
            'gar_nichts': 100,
            'kein_tag_aber_nacht': 80,
            'keine_nacht_aber_tag': 80,
            'tag_bevorzugt': 30,
            'nacht_bevorzugt': 30,
            'zusatzarbeit': 20,
        }
        return prioritaeten.get(self.wunsch, 0)


# ============================================
# 5. SCHICHT (braucht Schichtplan, Schichttyp, Mitarbeiter)
# ============================================

class Schicht(models.Model):
    """Einzelne Schichtzuweisung"""
    schichtplan = models.ForeignKey(
        Schichtplan,
        on_delete=models.CASCADE,
        related_name='schichten'
    )
    mitarbeiter = models.ForeignKey(
        'arbeitszeit.Mitarbeiter',
        on_delete=models.CASCADE,
        related_name='schichten'
    )
    datum = models.DateField()
    schichttyp = models.ForeignKey(
        Schichttyp,
        on_delete=models.PROTECT
    )
    
    abweichende_start_zeit = models.TimeField(null=True, blank=True)
    abweichende_ende_zeit = models.TimeField(null=True, blank=True)
    bemerkungen = models.TextField(blank=True)
    
    class Meta:
        verbose_name = "Schicht"
        verbose_name_plural = "Schichten"
        unique_together = [['schichtplan', 'mitarbeiter', 'datum', 'schichttyp']]
        ordering = ['datum', 'schichttyp__start_zeit']
    
    def __str__(self):
        return f"{self.mitarbeiter.vollname} - {self.datum} - {self.schichttyp.kuerzel}"
    
    @property
    def start_zeit(self):
        return self.abweichende_start_zeit or self.schichttyp.start_zeit
    
    @property
    def ende_zeit(self):
        return self.abweichende_ende_zeit or self.schichttyp.ende_zeit
    
    def clean(self):
        # Datum muss im Schichtplan-Zeitraum liegen
        if self.datum < self.schichtplan.start_datum or self.datum > self.schichtplan.ende_datum:
            raise ValidationError("Datum liegt außerhalb des Schichtplans.")


# ============================================
# 6. SCHICHTTAUSCH (braucht Schicht)
# ============================================

class Schichttausch(models.Model):
    """Anfrage zum Tausch einer Schicht"""
    urspruengliche_schicht = models.ForeignKey(
        Schicht,
        on_delete=models.CASCADE,
        related_name='tausch_anfragen'
    )
    angeboten_von = models.ForeignKey(
        'arbeitszeit.Mitarbeiter',
        on_delete=models.CASCADE,
        related_name='angebotene_tausche'
    )
    gewuenschter_partner = models.ForeignKey(
        'arbeitszeit.Mitarbeiter',
        on_delete=models.CASCADE,
        related_name='erhaltene_tausch_anfragen',
        null=True,
        blank=True
    )
    
    STATUS_CHOICES = [
        ('offen', 'Offen'),
        ('angenommen', 'Angenommen'),
        ('abgelehnt', 'Abgelehnt'),
        ('genehmigt', 'Genehmigt'),
        ('abgebrochen', 'Abgebrochen'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offen')
    
    nachricht = models.TextField(blank=True)
    erstellt_am = models.DateTimeField(auto_now_add=True)
    bearbeitet_am = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Schichttausch"
        verbose_name_plural = "Schichttausche"
        ordering = ['-erstellt_am']
    
    def __str__(self):
        return f"{self.angeboten_von.vollname} - {self.urspruengliche_schicht.datum}"