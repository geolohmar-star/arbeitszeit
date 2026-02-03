"""
Django Models für Arbeitszeitverwaltung
"""
from unicodedata import decimal
from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError

#WorkCalendar
from decimal import Decimal
import calendar
from workalendar.europe import NorthRhineWestphalia



#WorkCalendar
class MonatlicheArbeitszeitSoll(models.Model):
    """
    Berechnet und speichert Soll-Arbeitsstunden pro Mitarbeiter und Monat.
    Berücksichtigt Feiertage in NRW.
    """
    
    mitarbeiter = models.ForeignKey(
        'Mitarbeiter',
        on_delete=models.CASCADE,
        related_name='monatliche_soll_zeiten'
    )
    
    jahr = models.IntegerField(verbose_name="Jahr")
    monat = models.IntegerField(
        verbose_name="Monat",
        help_text="1=Januar, 12=Dezember"
    )
    
    # Berechnete Werte
    arbeitstage_gesamt = models.IntegerField(
        verbose_name="Arbeitstage gesamt",
        help_text="Alle Werktage (Mo-Fr) im Monat"
    )
    
    feiertage_anzahl = models.IntegerField(
        default=0,
        verbose_name="Anzahl Feiertage",
        help_text="Feiertage in NRW, die auf Werktage fallen"
    )
    
    arbeitstage_effektiv = models.IntegerField(
        verbose_name="Effektive Arbeitstage",
        help_text="Arbeitstage minus Feiertage"
    )
    
    wochenstunden = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name="Wochenstunden",
        help_text="Vertragliche Wochenstunden des Mitarbeiters"
    )
    
    soll_stunden = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        verbose_name="Soll-Stunden",
        help_text="Berechnete Soll-Arbeitsstunden für diesen Monat"
    )
    
    # Zusatzinfos
    feiertage_liste = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Feiertage",
        help_text="Liste der Feiertage mit Datum und Name"
    )
    
    berechnet_am = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Monatliches Arbeitszeitlimit"
        verbose_name_plural = "Monatliche Arbeitszeitlimits"
        unique_together = ['mitarbeiter', 'jahr', 'monat']
        ordering = ['jahr', 'monat', 'mitarbeiter']
    
    def __str__(self):
        monat_name = calendar.month_name[self.monat]
        return f"{self.mitarbeiter.vollname} - {monat_name} {self.jahr}: {self.soll_stunden}h"
    
    @classmethod
    def berechne_und_speichere(cls, mitarbeiter, jahr, monat):
        """
        Berechnet die Soll-Stunden für einen Mitarbeiter und Monat.
        Holt Wochenstunden aus der aktuell gültigen Vereinbarung!
        
        Args:
            mitarbeiter: Mitarbeiter-Objekt
            jahr: Jahr (z.B. 2026)
            monat: Monat (1-12)
        
        Returns:
            MonatlicheArbeitszeitSoll-Objekt
        
        Raises:
            ValueError: Wenn keine gültige Vereinbarung gefunden wird
        """
        import datetime
        import calendar
        from decimal import Decimal
        from workalendar.europe import NorthRhineWestphalia
        
        # 1. Hole Wochenstunden aus aktueller Vereinbarung
        # Stichtag = Mitte des Monats (falls Vereinbarung im Monat wechselt)
        stichtag = datetime.date(jahr, monat, 15)
        
        # Hole Vereinbarung zum Stichtag
        vereinbarung = mitarbeiter.get_aktuelle_vereinbarung(stichtag)
        
        if not vereinbarung:
            raise ValueError(
                f"Keine gültige Arbeitszeitvereinbarung für {mitarbeiter.vollname} "
                f"im {calendar.month_name[monat]} {jahr} gefunden! "
                f"Bitte erstelle eine Vereinbarung mit Status 'Genehmigt'."
            )
        
        if not vereinbarung.wochenstunden:
            raise ValueError(
                f"Vereinbarung für {mitarbeiter.vollname} hat keine Wochenstunden! "
                f"Bitte ergänze die Wochenstunden in Vereinbarung #{vereinbarung.pk}."
            )
        
        wochenstunden = vereinbarung.wochenstunden
        
        # 2. Berechne Arbeitstage und Feiertage
        cal = NorthRhineWestphalia()
        _, letzter_tag = calendar.monthrange(jahr, monat)
        
        arbeitstage_gesamt = 0
        feiertage = []
        
        for tag in range(1, letzter_tag + 1):
            datum = datetime.date(jahr, monat, tag)
            wochentag = datum.weekday()
            
            # Nur Werktage (Mo-Fr) zählen
            if wochentag < 5:
                arbeitstage_gesamt += 1
                
                # Prüfe ob Feiertag
                if cal.is_holiday(datum):
                    feiertag_name = cal.get_holiday_label(datum)
                    feiertage.append({
                        'datum': datum.isoformat(),
                        'name': feiertag_name,
                        'wochentag': calendar.day_name[wochentag]
                    })
        
        feiertage_anzahl = len(feiertage)
        arbeitstage_effektiv = arbeitstage_gesamt - feiertage_anzahl
        
        # 3. Berechne Soll-Stunden
        # Formel: (Wochenstunden / 5 Tage) × Effektive Arbeitstage
        tagesstunden = wochenstunden / Decimal('5')
        soll_stunden = tagesstunden * Decimal(str(arbeitstage_effektiv))
        
        # Runde auf 2 Nachkommastellen
        soll_stunden = soll_stunden.quantize(Decimal('0.01'))
        
        # 4. Speichern oder aktualisieren
        obj, created = cls.objects.update_or_create(
            mitarbeiter=mitarbeiter,
            jahr=jahr,
            monat=monat,
            defaults={
                'arbeitstage_gesamt': arbeitstage_gesamt,
                'feiertage_anzahl': feiertage_anzahl,
                'arbeitstage_effektiv': arbeitstage_effektiv,
                'wochenstunden': wochenstunden,  # ← Aus Vereinbarung!
                'soll_stunden': soll_stunden,
                'feiertage_liste': feiertage,
            }
        )
        
        return obj
    
    @classmethod
    def berechne_fuer_alle_mitarbeiter(cls, jahr, monat):
        """
        Berechnet Soll-Stunden für alle aktiven Mitarbeiter.
        
        Args:
            jahr: Jahr
            monat: Monat (1-12)
        
        Returns:
            Liste der erstellten/aktualisierten Objekte
        """
        from arbeitszeit.models import Mitarbeiter
        
        aktive_mitarbeiter = Mitarbeiter.objects.filter(aktiv=True)
        ergebnisse = []
        
        for ma in aktive_mitarbeiter:
            obj = cls.berechne_und_speichere(ma, jahr, monat)
            ergebnisse.append(obj)
        
        return ergebnisse
    
    @property
    def soll_stunden_formatiert(self):
        """Gibt Soll-Stunden als String zurück (z.B. '168:00h')"""
        stunden = int(self.soll_stunden)
        minuten = int((self.soll_stunden - stunden) * 60)
        return f"{stunden}:{minuten:02d}h"
    
    @property
    def monat_name(self):
        """Gibt Monatsnamen zurück"""
        return calendar.month_name[self.monat]
    



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
    SCHICHT_TYP_CHOICES = [
        ('typ_a', 'Typ A - Normale Planung'),
        ('typ_b', 'Typ B - Min. 4T + 4N pro Monat'),
    ]
    
    schicht_typ = models.CharField(
        max_length=10,
        choices=SCHICHT_TYP_CHOICES,
        default='typ_a',
        verbose_name="Schichttyp",
        help_text="Typ A: Normale Planung | Typ B: Mind. 4 Tag- UND 4 Nachtschichten/Monat"
    )
    #### Soll ZEITEN FÜR MITARBEITER ####
    def get_aktuelle_vereinbarung(self, stichtag=None):
        """Holt die zum Stichtag gültige Arbeitszeitvereinbarung."""
        from django.utils import timezone
        from django.db.models import Q
        
        if stichtag is None:
            stichtag = timezone.now().date()
        
        return self.arbeitszeitvereinbarungen.filter(
            status__in=['aktiv', 'genehmigt'],  # ← Beide Status akzeptieren!
            gueltig_ab__lte=stichtag
        ).filter(
            Q(gueltig_bis__isnull=True) | Q(gueltig_bis__gte=stichtag)
        ).order_by('-gueltig_ab').first()
        
    def get_wochenstunden(self, stichtag=None):
        """
        Holt die Wochenstunden aus der aktuellen Vereinbarung.
        
        Args:
            stichtag (date): Datum für das die Wochenstunden gelten sollen
        
        Returns:
            Decimal: Wochenstunden oder None wenn keine Vereinbarung
        """
        vereinbarung = self.get_aktuelle_vereinbarung(stichtag)
        
        if vereinbarung:
            return vereinbarung.wochenstunden
        
        return None
    
    def get_aktuelle_arbeitszeit_info(self):
        """
        Gibt Informationen zur aktuellen Arbeitszeit zurück.
        Wird im Dashboard verwendet.
        
        Returns:
            dict mit 'vereinbarung', 'wochenstunden', 'antragsart', etc.
        """
        vereinbarung = self.get_aktuelle_vereinbarung()
        
        if vereinbarung:
            return {
                'vereinbarung': vereinbarung,
                'wochenstunden': vereinbarung.wochenstunden,
                'antragsart': vereinbarung.get_antragsart_display(),
                'status': vereinbarung.get_status_display(),
                'gueltig_ab': vereinbarung.gueltig_ab,
                'gueltig_bis': vereinbarung.gueltig_bis,
                'ist_befristet': vereinbarung.gueltig_bis is not None,
            }
        
        return None
    #WorkCalendar
    def get_soll_stunden_monat(self, jahr, monat):
        """
        Gibt Soll-Stunden für einen bestimmten Monat zurück.
        Berechnet automatisch, wenn noch nicht vorhanden.
        
        Args:
            jahr: Jahr (z.B. 2025)
            monat: Monat (1-12)
        
        Returns:
            Decimal: Soll-Stunden
        """
        from arbeitszeit.models import MonatlicheArbeitszeitSoll
        
        soll = MonatlicheArbeitszeitSoll.objects.filter(
            mitarbeiter=self,
            jahr=jahr,
            monat=monat
        ).first()
        
        if not soll:
            # Automatisch berechnen
            soll = MonatlicheArbeitszeitSoll.berechne_und_speichere(self, jahr, monat)
        
        return soll.soll_stunden
    
    def get_soll_stunden_aktueller_monat(self):
        """Gibt Soll-Stunden für den aktuellen Monat zurück"""
        heute = timezone.now().date()
        return self.get_soll_stunden_monat(heute.year, heute.month)
   
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
    
    nur_zusatzarbeiten = models.BooleanField(
        default=False,
        help_text="Nur für Zusatzarbeiten verfügbar (12h)"
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

    # NEU: Erlaubte Arbeitstage (individuelle Vereinbarung)
    # Null = alle Tage erlaubt
    erlaubte_wochentage = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Erlaubte Arbeitstage",
        help_text="Nur bestimmte Tage: [0]=Mo, [1]=Di, [2]=Mi, [3]=Do, [4]=Fr, [5]=Sa, [6]=So. Leer = alle Tage erlaubt."
    )

    # NEU: Keine Zusatzdienste
    keine_zusatzdienste = models.BooleanField(
        default=False,
        verbose_name="Keine Zusatzdienste",
        help_text="Wenn aktiv: MA wird NICHT in Zusatzdienste eingeteilt"
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
        # 1. PRIORITÄT: Wenn Einzeltage (Montag, Dienstag...) existieren, nimm diese!
        tage = self.tagesarbeitszeiten.all()
        if tage.exists():
            total_minuten = sum(t.zeit_in_minuten for t in tage)
            anzahl_wochen = tage.values('woche').distinct().count() or 1
            minuten_pro_woche = total_minuten / anzahl_wochen
            
            stunden = int(minuten_pro_woche // 60)
            minuten = int(round(minuten_pro_woche % 60))
            return f"{stunden}:{minuten:02d}h"

        # 2. PRIORITÄT: Wenn keine Einzeltage da sind, nimm das Feld 'wochenstunden'
        if self.wochenstunden and self.wochenstunden > 0:
            stunden = int(self.wochenstunden)
            minuten = int(round((self.wochenstunden - stunden) * 60))
            return f"{stunden}:{minuten:02d}h"

        # 3. FALLBACK: Wenn gar nichts gefunden wurde
        return "0:00h"
        
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
        """Berechnet die durchschnittliche Tagesarbeitszeit für beide Typen"""
        total_wochen_minuten = 0

        # Fall 1: Regelmäßige Arbeitszeit
        if self.arbeitszeit_typ == 'regelmaessig' and self.wochenstunden:
            # Wochenstunden (Decimal) in Minuten umrechnen
            total_wochen_minuten = float(self.wochenstunden) * 60

        # Fall 2: Individuelle Verteilung
        elif self.arbeitszeit_typ == 'individuell':
            tage = self.tagesarbeitszeiten.all()
            if tage.exists():
                summe_minuten = sum(t.zeit_in_minuten for t in tage)
                anzahl_wochen = tage.values('woche').distinct().count() or 1
                # Durchschnittliche Minuten pro Woche
                total_wochen_minuten = summe_minuten / anzahl_wochen

        # Berechnung des Tagesdurchschnitts (basierend auf einer 5-Tage-Woche)
        if total_wochen_minuten > 0:
            # Wochenminuten durch 5 Tage teilen
            tages_minuten = total_wochen_minuten / 5
            
            stunden = int(tages_minuten // 60)
            minuten = int(round(tages_minuten % 60))
            return f"{stunden}:{minuten:02d}h"

        return "0:00h"
    


from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

class Tagesarbeitszeit(models.Model):
    """
    Speichert die Arbeitszeit für einen einzelnen Wochentag einer Arbeitszeitvereinbarung.
    Zeitwert wird als HMM gespeichert (z.B. 830 für 08:30).
    """

    vereinbarung = models.ForeignKey(
        'Arbeitszeitvereinbarung',
        related_name="tagesarbeitszeiten",
        on_delete=models.CASCADE
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
    wochentag = models.CharField(max_length=10, choices=WOCHENTAG_CHOICES)
    
    # Zeitwert im Format HMM (z.B. 830 für 8:30)
    zeitwert = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(2359)]
    )

    woche = models.IntegerField(default=1)  # z. B. 1 oder 2

    class Meta:
        verbose_name = "Tagesarbeitszeit"
        verbose_name_plural = "Tagesarbeitszeiten"
        unique_together = ['vereinbarung', 'wochentag', 'woche']
        ordering = ['woche', 'wochentag']

    def __str__(self):
        if self.zeitwert is None:
            return f"{self.get_wochentag_display()}: —"
        return f"{self.get_wochentag_display()}: {self.formatierte_zeit}"
    

    @property
    def stunden(self):
        # Wenn zeitwert 468 ist: 468 // 60 = 7
        return self.zeitwert // 60
    @property
    def minuten(self):
        # Wenn zeitwert 468 ist: 468 % 60 = 48
        return self.zeitwert % 60
    
    def formatierte_zeit(self):
        """
        Wandelt den gespeicherten HMM-Zeitwert in HH:MM um.
        Beispiel: 830 -> 08:30
        """
        if self.zeitwert is None:
            return "—"
        return f"{self.stunden:02d}:{self.minuten:02d}"

    @property
    def zeit_in_minuten(self):
        # Da der Wert schon in Minuten vorliegt, einfach zurückgeben
        return self.zeitwert if self.zeitwert else 0


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
        
        
#####Soll Zeit Berechnung mit Feiertagen #####        
@classmethod
def berechne_und_speichere(cls, mitarbeiter, jahr, monat):
    """
    Berechnet die Soll-Stunden für einen Mitarbeiter und Monat.
    Verwendet die tatsächliche Arbeitszeitvereinbarung!
    """
  
    
    # 1. Hole Wochenstunden aus Vereinbarung
    # Stichtag = Mitte des Monats (für den Fall dass sich was ändert)
    stichtag = datetime.date(jahr, monat, 15)
    
    wochenstunden = mitarbeiter.get_wochenstunden(stichtag)
    
    if wochenstunden is None:
        raise ValueError(
            f"Keine gültige Arbeitszeitvereinbarung für {mitarbeiter.vollname} "
            f"im {calendar.month_name[monat]} {jahr} gefunden!"
        )
    
    # 2. Berechne Arbeitstage und Feiertage
    cal = NorthRhineWestphalia()
    _, letzter_tag = calendar.monthrange(jahr, monat)
    
    arbeitstage_gesamt = 0
    feiertage = []
    
    for tag in range(1, letzter_tag + 1):
        datum = datetime.date(jahr, monat, tag)
        wochentag = datum.weekday()
        
        if wochentag < 5:  # Mo-Fr
            arbeitstage_gesamt += 1
            
            if cal.is_holiday(datum):
                feiertag_name = cal.get_holiday_label(datum)
                feiertage.append({
                    'datum': datum.isoformat(),
                    'name': feiertag_name,
                    'wochentag': calendar.day_name[wochentag]
                })
    
    feiertage_anzahl = len(feiertage)
    arbeitstage_effektiv = arbeitstage_gesamt - feiertage_anzahl
    
    # 3. Berechne Soll-Stunden
    tagesstunden = wochenstunden / Decimal('5')
    soll_stunden = tagesstunden * Decimal(str(arbeitstage_effektiv))
    soll_stunden = soll_stunden.quantize(Decimal('0.01'))
    
    # 4. Speichern
    obj, created = cls.objects.update_or_create(
        mitarbeiter=mitarbeiter,
        jahr=jahr,
        monat=monat,
        defaults={
            'arbeitstage_gesamt': arbeitstage_gesamt,
            'feiertage_anzahl': feiertage_anzahl,
            'arbeitstage_effektiv': arbeitstage_effektiv,
            'wochenstunden': wochenstunden,  # ← Tatsächliche Wochenstunden!
            'soll_stunden': soll_stunden,
            'feiertage_liste': feiertage,
        }
    )
    
    return obj