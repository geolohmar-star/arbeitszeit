from django.contrib import admin
from .models import (
    Mitarbeiter, 
    Arbeitszeitvereinbarung, 
    Tagesarbeitszeit,
    ArbeitszeitHistorie, 
    Urlaubsanspruch, 
    Zeiterfassung
)

#Workcalendar
from .models import MonatlicheArbeitszeitSoll
from django.utils.html import format_html
import calendar

#WorkCalendar
@admin.register(MonatlicheArbeitszeitSoll)
class MonatlicheArbeitszeitSollAdmin(admin.ModelAdmin):
    list_display = [
        'mitarbeiter',
        'jahr',
        'get_monat_name',
        'wochenstunden',
        'arbeitstage_effektiv',
        'feiertage_anzahl',
        'get_soll_stunden_formatiert',
        'berechnet_am'
    ]
    
    list_filter = [
        'jahr',
        'monat',
        'mitarbeiter__abteilung',
    ]
    
    search_fields = [
        'mitarbeiter__nachname',
        'mitarbeiter__vorname',
        'mitarbeiter__personalnummer'
    ]
    
    readonly_fields = [
        'arbeitstage_gesamt',
        'feiertage_anzahl',
        'arbeitstage_effektiv',
        'soll_stunden',
        'get_feiertage_display',
        'berechnet_am'
    ]
    
    fieldsets = (
        ('Mitarbeiter & Zeitraum', {
            'fields': ('mitarbeiter', 'jahr', 'monat')
        }),
        ('Berechnete Werte', {
            'fields': (
                'wochenstunden',
                'arbeitstage_gesamt',
                'feiertage_anzahl',
                'arbeitstage_effektiv',
                'soll_stunden',
            )
        }),
        ('Feiertage', {
            'fields': ('get_feiertage_display',),
            'classes': ('collapse',)
        }),
        ('Meta', {
            'fields': ('berechnet_am',),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['neu_berechnen']
    
    def get_monat_name(self, obj):
        return calendar.month_name[obj.monat]
    get_monat_name.short_description = 'Monat'
    
    def get_soll_stunden_formatiert(self, obj):
        return obj.soll_stunden_formatiert
    get_soll_stunden_formatiert.short_description = 'Soll-Stunden'
    
    def get_feiertage_display(self, obj):
        """Zeigt Feiertage formatiert an"""
        if not obj.feiertage_liste:
            return "Keine Feiertage"
        
        html = "<ul>"
        for ft in obj.feiertage_liste:
            html += f"<li><strong>{ft['datum']}</strong> ({ft['wochentag']}): {ft['name']}</li>"
        html += "</ul>"
        
        return format_html(html)
    get_feiertage_display.short_description = 'Feiertage im Monat'
    
    def neu_berechnen(self, request, queryset):
        """Admin-Action: Neu berechnen"""
        count = 0
        for obj in queryset:
            MonatlicheArbeitszeitSoll.berechne_und_speichere(
                obj.mitarbeiter,
                obj.jahr,
                obj.monat
            )
            count += 1
        
        self.message_user(
            request,
            f"{count} Soll-Stunden erfolgreich neu berechnet!"
        )
    neu_berechnen.short_description = "Soll-Stunden neu berechnen"

@admin.register(Mitarbeiter)
class MitarbeiterAdmin(admin.ModelAdmin):
    list_display = [
        'personalnummer', 
        'nachname', 
        'vorname',
        'get_wochenstunden_display',
        'schichtplan_kennung',
        'schicht_typ',  # NEU
        'verfuegbarkeit',
        'aktiv'
    ]
    
    list_filter = [
        'aktiv', 
        'standort', 
        'rolle',
        'schicht_typ',  # NEU
        'verfuegbarkeit'
    ]
    
    fieldsets = (
        ('Basisdaten', {
            'fields': (
                'user', 'personalnummer', 'vorname', 'nachname',
                'abteilung', 'standort', 'rolle', 'eintrittsdatum', 'aktiv'
            )
        }),
        ('Schichtplan-Zuordnung', {
            'fields': (
                'schichtplan_kennung',
                'schicht_typ',  # NEU
            )
        }),
        ('Schichtfähigkeiten', {
            'fields': (
                'kann_tagschicht',
                'kann_nachtschicht',
                'nur_zusatzarbeiten',
            )
        }),
        ('Präferenzen & Einschränkungen', {
            'fields': (
                'verfuegbarkeit',
                'nachtschicht_nur_wochenende',
                'nur_zusatzdienste_wochentags',
                'max_wochenenden_pro_monat',
                'max_schichten_pro_monat',
                'max_aufeinanderfolgende_tage',
                'planungs_prioritaet',
                'erlaubte_wochentage',      # ← NEU
                'keine_zusatzdienste',      # ← NEU
            )
        }),
        ('Bemerkungen', {
            'fields': (
                'schichtplan_bemerkungen',
                'schichtplan_einschraenkungen',
            ),
            'classes': ('collapse',)
        }),
    )
    def get_wochenstunden_display(self, obj):
        """Zeigt aktuelle Wochenstunden mit Warnung wenn keine Vereinbarung"""
        wochenstunden = obj.get_wochenstunden()
        
        if wochenstunden:
            return format_html(
                '<span style="color: green;">{}h/Woche</span>',
                wochenstunden
            )
        else:
            return format_html(
                '<span style="color: red;" title="{}">⚠️ Keine</span>',
                "Keine Arbeitszeitvereinbarung"
            )  # ← MIT Platzhalter {} und Wert
            
    get_wochenstunden_display.short_description = 'Wochenstunden'
    get_wochenstunden_display.admin_order_field = 'arbeitszeitvereinbarungen__wochenstunden'



class TagesarbeitszeitInline(admin.TabularInline):
    model = Tagesarbeitszeit
    extra = 0
    fields = ['wochentag', 'zeitwert', 'formatierte_zeit']
    readonly_fields = ['formatierte_zeit']


@admin.register(Arbeitszeitvereinbarung)
class ArbeitszeitvereinbarungAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'get_mitarbeiter', 
        'antragsart', 
        'arbeitszeit_typ',
        'wochenstunden',
        'status', 
        'gueltig_ab',
        'gueltig_bis'
    ]
    list_filter = ['status', 'antragsart', 'arbeitszeit_typ', 'telearbeit']
    search_fields = [
        'mitarbeiter__vorname', 
        'mitarbeiter__nachname', 
        'mitarbeiter__personalnummer'
    ]
    date_hierarchy = 'gueltig_ab'
    
    fieldsets = (
        ('Mitarbeiter', {
            'fields': ('mitarbeiter',)
        }),
        ('Vereinbarung', {
            'fields': (
                'antragsart',
                'arbeitszeit_typ',
                'wochenstunden',
                'gueltig_ab',
                'gueltig_bis',
                'telearbeit'
            )
        }),
        ('Status', {
            'fields': (
                'status',
                'genehmigt_von',
                'genehmigt_am'
            )
        }),
        ('Beendigung', {
            'fields': (
                'beendigung_beantragt',
                'beendigung_datum'
            ),
            'classes': ('collapse',)
        }),
        ('Notizen', {
            'fields': ('bemerkungen',),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['genehmigt_am']
    inlines = [TagesarbeitszeitInline]
    
    def get_mitarbeiter(self, obj):
        """Sichere Anzeige des Mitarbeiters"""
        if obj.mitarbeiter:
            return obj.mitarbeiter.vollname
        return '-'
    get_mitarbeiter.short_description = 'Mitarbeiter'
    get_mitarbeiter.admin_order_field = 'mitarbeiter__nachname'


@admin.register(Tagesarbeitszeit)
class TagesarbeitszeitAdmin(admin.ModelAdmin):
    list_display = ['vereinbarung', 'wochentag', 'formatierte_zeit']
    list_filter = ['wochentag']
    search_fields = ['vereinbarung__mitarbeiter__nachname']


@admin.register(ArbeitszeitHistorie)
class ArbeitszeitHistorieAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'get_mitarbeiter',
        'aenderung_am',
        'alter_status',
        'neuer_status',
        'get_geaendert_von'
    ]
    list_filter = ['alter_status', 'neuer_status', 'aenderung_am']
    search_fields = [
        'vereinbarung__mitarbeiter__vorname',
        'vereinbarung__mitarbeiter__nachname'
    ]
    date_hierarchy = 'aenderung_am'
    readonly_fields = ['aenderung_am']
    
    def get_mitarbeiter(self, obj):
        """Sichere Anzeige des Mitarbeiters"""
        if obj.vereinbarung and obj.vereinbarung.mitarbeiter:
            return obj.vereinbarung.mitarbeiter.vollname
        return '-'
    get_mitarbeiter.short_description = 'Mitarbeiter'
    
    def get_geaendert_von(self, obj):
        """Sichere Anzeige des ändernden Users"""
        if obj.aenderung_durch:
            return obj.aenderung_durch.get_full_name() or obj.aenderung_durch.username
        return '-'
    get_geaendert_von.short_description = 'Geändert von'


@admin.register(Urlaubsanspruch)
class UrlaubsanspruchAdmin(admin.ModelAdmin):
    list_display = [
        'get_mitarbeiter',
        'jahr',
        'jahresurlaubstage_anteilig',
        'genommene_urlaubstage',
        'resturlaubstage'
    ]
    list_filter = ['jahr']
    search_fields = ['mitarbeiter__vorname', 'mitarbeiter__nachname']
    
    def get_mitarbeiter(self, obj):
        """Sichere Anzeige des Mitarbeiters"""
        if obj.mitarbeiter:
            return obj.mitarbeiter.vollname
        return '-'
    get_mitarbeiter.short_description = 'Mitarbeiter'
    get_mitarbeiter.admin_order_field = 'mitarbeiter__nachname'


@admin.register(Zeiterfassung)
class ZeiterfassungAdmin(admin.ModelAdmin):
    list_display = [
        'get_mitarbeiter',
        'datum',
        'arbeitsbeginn',
        'arbeitsende',
        'arbeitszeit_formatiert',
        'art'
    ]
    list_filter = ['art', 'datum']
    search_fields = ['mitarbeiter__vorname', 'mitarbeiter__nachname']
    date_hierarchy = 'datum'
    
    fieldsets = (
        ('Mitarbeiter & Datum', {
            'fields': ('mitarbeiter', 'datum')
        }),
        ('Arbeitszeit', {
            'fields': (
                'arbeitsbeginn',
                'arbeitsende',
                'pause_minuten',
                'arbeitszeit_minuten'
            )
        }),
        ('Art & Bemerkung', {
            'fields': ('art', 'bemerkung')
        }),
    )
    
    readonly_fields = ['arbeitszeit_minuten']
    
    def get_mitarbeiter(self, obj):
        """Sichere Anzeige des Mitarbeiters"""
        if obj.mitarbeiter:
            return obj.mitarbeiter.vollname
        return '-'
    get_mitarbeiter.short_description = 'Mitarbeiter'
    get_mitarbeiter.admin_order_field = 'mitarbeiter__nachname'