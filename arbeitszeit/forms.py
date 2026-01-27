"""
Django Forms für Arbeitszeitverwaltung
"""
from django import forms
from django.forms import inlineformset_factory
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import (
    Mitarbeiter, Arbeitszeitvereinbarung, Tagesarbeitszeit,
    Zeiterfassung, Urlaubsanspruch
)


class ArbeitszeitvereinbarungForm(forms.ModelForm):
    """Formular für Arbeitszeitvereinbarung"""
    
    class Meta:
        model = Arbeitszeitvereinbarung
        fields = [
            'antragsart', 'arbeitszeit_typ', 'wochenstunden',
            'gueltig_ab', 'gueltig_bis', 'telearbeit',
            'beendigung_beantragt', 'beendigung_datum', 'bemerkungen'
        ]
        widgets = {
            'antragsart': forms.RadioSelect(),
            'arbeitszeit_typ': forms.RadioSelect(),
            'wochenstunden': forms.NumberInput(attrs={
                'min': '2',
                'max': '48',
                'step': '0.01',
                'placeholder': 'z.B. 38'
            }),
            'gueltig_ab': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'gueltig_bis': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'beendigung_datum': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'telearbeit': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'beendigung_beantragt': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
            'bemerkungen': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control'
            }),
        }
        labels = {
            'antragsart': 'Ich beantrage folgendes',
            'arbeitszeit_typ': 'Art der Arbeitszeitverteilung',
            'wochenstunden': 'Wochenstunden',
            'gueltig_ab': 'Gültig ab',
            'gueltig_bis': 'Gültig bis',
            'telearbeit': 'In Telearbeit',
            'beendigung_beantragt': 'Beendigung der Vereinbarung',
            'beendigung_datum': 'Beendigung bis zum',
            'bemerkungen': 'Bemerkungen',
        }
    
    def __init__(self, *args, **kwargs):
        self.mitarbeiter = kwargs.pop('mitarbeiter', None)
        super().__init__(*args, **kwargs)
        
        # Wochenstunden ist nur bei regelmäßig erforderlich
        self.fields['wochenstunden'].required = False
        self.fields['gueltig_bis'].required = False
        self.fields['beendigung_datum'].required = False
    
    def clean(self):
        cleaned_data = super().clean()
        arbeitszeit_typ = cleaned_data.get('arbeitszeit_typ')
        wochenstunden = cleaned_data.get('wochenstunden')
        gueltig_ab = cleaned_data.get('gueltig_ab')
        gueltig_bis = cleaned_data.get('gueltig_bis')
        beendigung_beantragt = cleaned_data.get('beendigung_beantragt')
        beendigung_datum = cleaned_data.get('beendigung_datum')
        
        # Validierung: Wochenstunden bei regelmäßig erforderlich
        if arbeitszeit_typ == 'regelmaessig' and not wochenstunden:
            raise ValidationError({
                'wochenstunden': 'Wochenstunden sind bei regelmäßiger Arbeitszeit erforderlich.'
            })
        
        # Validierung: gueltig_bis muss nach gueltig_ab sein
        if gueltig_ab and gueltig_bis and gueltig_bis < gueltig_ab:
            raise ValidationError({
                'gueltig_bis': 'Das Ende-Datum muss nach dem Start-Datum liegen.'
            })
        
        # Validierung: Beendigungsdatum bei Beendigung erforderlich
        if beendigung_beantragt and not beendigung_datum:
            raise ValidationError({
                'beendigung_datum': 'Beendigungsdatum ist erforderlich wenn Beendigung beantragt wird.'
            })
        
        # Validierung: Keine Überschneidung mit anderen aktiven Vereinbarungen
        if self.mitarbeiter and gueltig_ab:
            existing = Arbeitszeitvereinbarung.objects.filter(
                mitarbeiter=self.mitarbeiter,
                status__in=['genehmigt', 'aktiv']
            ).exclude(pk=self.instance.pk if self.instance else None)
            
            for vereinbarung in existing:
                # Prüfe Überschneidung
                if vereinbarung.gueltig_bis:
                    if gueltig_ab <= vereinbarung.gueltig_bis:
                        if not gueltig_bis or gueltig_bis >= vereinbarung.gueltig_ab:
                            raise ValidationError({
                                'gueltig_ab': f'Überschneidung mit bestehender Vereinbarung ab {vereinbarung.gueltig_ab}'
                            })
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        if self.mitarbeiter:
            instance.mitarbeiter = self.mitarbeiter
        
        # Status setzen wenn neu
        if not instance.pk:
            instance.status = 'beantragt'
        
        if commit:
            instance.save()
        
        return instance


class TagesarbeitszeitForm(forms.ModelForm):
    """Formular für einzelne Tagesarbeitszeit"""
    
    class Meta:
        model = Tagesarbeitszeit
        fields = ['wochentag', 'zeitwert']
        widgets = {
            'wochentag': forms.Select(attrs={'class': 'form-control'}),
            'zeitwert': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Zeitwert-Optionen generieren (2:00 - 12:00)
        choices = [('', '--')]
        for hour in range(2, 13):
            max_minute = 1 if hour == 12 else 60
            for minute in range(0, max_minute):
                value = hour * 100 + minute
                display = f"{hour}:{minute:02d}h"
                choices.append((value, display))
        
        self.fields['zeitwert'].widget = forms.Select(
            choices=choices,
            attrs={'class': 'form-control'}
        )


# Formset für Tagesarbeitszeiten
TagesarbeitszeitFormSet = inlineformset_factory(
    Arbeitszeitvereinbarung,
    Tagesarbeitszeit,
    form=TagesarbeitszeitForm,
    extra=5,  # Montag bis Freitag
    max_num=5,
    can_delete=False,
    fields=['wochentag', 'zeitwert']
)


class ZeiterfassungForm(forms.ModelForm):
    """Formular für Zeiterfassung"""
    
    class Meta:
        model = Zeiterfassung
        fields = [
            'datum', 'arbeitsbeginn', 'arbeitsende',
            'pause_minuten', 'art', 'bemerkung'
        ]
        widgets = {
            'datum': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'arbeitsbeginn': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'form-control'
            }),
            'arbeitsende': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'form-control'
            }),
            'pause_minuten': forms.NumberInput(attrs={
                'min': '0',
                'max': '120',
                'class': 'form-control',
                'placeholder': 'Minuten'
            }),
            'art': forms.Select(attrs={'class': 'form-control'}),
            'bemerkung': forms.Textarea(attrs={
                'rows': 3,
                'class': 'form-control'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.mitarbeiter = kwargs.pop('mitarbeiter', None)
        super().__init__(*args, **kwargs)
        
        # Standardwerte
        if not self.instance.pk:
            self.fields['datum'].initial = timezone.now().date()
            self.fields['pause_minuten'].initial = 30
    
    def clean(self):
        cleaned_data = super().clean()
        arbeitsbeginn = cleaned_data.get('arbeitsbeginn')
        arbeitsende = cleaned_data.get('arbeitsende')
        art = cleaned_data.get('art')
        
        # Validierung: Bei normaler Arbeit sind Zeiten erforderlich
        if art in ['buero', 'homeoffice']:
            if not arbeitsbeginn or not arbeitsende:
                raise ValidationError(
                    'Bei Büro/Homeoffice sind Arbeitsbeginn und -ende erforderlich.'
                )
            
            # Arbeitsende muss nach Arbeitsbeginn sein (am selben oder nächsten Tag)
            if arbeitsbeginn and arbeitsende:
                from datetime import datetime, timedelta
                datum = cleaned_data.get('datum', timezone.now().date())
                beginn = datetime.combine(datum, arbeitsbeginn)
                ende = datetime.combine(datum, arbeitsende)
                
                # Ende kann am nächsten Tag sein (Nachtschicht)
                if ende < beginn:
                    ende += timedelta(days=1)
                
                # Max 16 Stunden Arbeitszeit
                differenz = (ende - beginn).total_seconds() / 3600
                if differenz > 16:
                    raise ValidationError(
                        'Arbeitszeit darf 16 Stunden nicht überschreiten.'
                    )
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        if self.mitarbeiter:
            instance.mitarbeiter = self.mitarbeiter
        
        if commit:
            instance.save()
        
        return instance


class UrlaubsanspruchForm(forms.ModelForm):
    """Formular für Urlaubsanspruch"""
    
    class Meta:
        model = Urlaubsanspruch
        fields = [
            'jahr', 'jahresurlaubstage_vollzeit',
            'jahresurlaubstage_anteilig', 'genommene_urlaubstage'
        ]
        widgets = {
            'jahr': forms.NumberInput(attrs={
                'min': '2020',
                'max': '2050',
                'class': 'form-control'
            }),
            'jahresurlaubstage_vollzeit': forms.NumberInput(attrs={
                'step': '0.5',
                'class': 'form-control'
            }),
            'jahresurlaubstage_anteilig': forms.NumberInput(attrs={
                'step': '0.5',
                'class': 'form-control',
                'readonly': True  # Wird automatisch berechnet
            }),
            'genommene_urlaubstage': forms.NumberInput(attrs={
                'step': '0.5',
                'class': 'form-control'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        self.mitarbeiter = kwargs.pop('mitarbeiter', None)
        super().__init__(*args, **kwargs)
        
        # Standardwerte
        if not self.instance.pk:
            self.fields['jahr'].initial = timezone.now().year
            self.fields['jahresurlaubstage_vollzeit'].initial = 30
    
    def clean(self):
        cleaned_data = super().clean()
        jahr = cleaned_data.get('jahr')
        
        # Validierung: Jahr nicht in der Zukunft
        if jahr and jahr > timezone.now().year + 1:
            raise ValidationError({
                'jahr': 'Jahr darf nicht mehr als 1 Jahr in der Zukunft liegen.'
            })
        
        # Validierung: Kein Duplikat für Mitarbeiter/Jahr
        if self.mitarbeiter and jahr:
            existing = Urlaubsanspruch.objects.filter(
                mitarbeiter=self.mitarbeiter,
                jahr=jahr
            ).exclude(pk=self.instance.pk if self.instance else None)
            
            if existing.exists():
                raise ValidationError({
                    'jahr': f'Urlaubsanspruch für {jahr} existiert bereits.'
                })
        
        return cleaned_data
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        if self.mitarbeiter:
            instance.mitarbeiter = self.mitarbeiter
            
            # Berechne anteiligen Urlaub basierend auf aktueller Arbeitszeit
            aktuelle_vereinbarung = self.mitarbeiter.get_aktuelle_vereinbarung()
            if aktuelle_vereinbarung and aktuelle_vereinbarung.wochenstunden:
                faktor = float(aktuelle_vereinbarung.wochenstunden) / 40.0  # 40h = Vollzeit
                instance.jahresurlaubstage_anteilig = float(instance.jahresurlaubstage_vollzeit) * faktor
        
        if commit:
            instance.save()
        
        return instance


class MitarbeiterForm(forms.ModelForm):
    """Formular für Mitarbeiter (Admin)"""
    
    class Meta:
        model = Mitarbeiter
        fields = [
            'user', 'personalnummer', 'nachname', 'vorname',
            'abteilung', 'standort', 'eintrittsdatum', 'aktiv'
        ]
        widgets = {
            'user': forms.Select(attrs={'class': 'form-control'}),
            'personalnummer': forms.TextInput(attrs={'class': 'form-control'}),
            'nachname': forms.TextInput(attrs={'class': 'form-control'}),
            'vorname': forms.TextInput(attrs={'class': 'form-control'}),
            'abteilung': forms.TextInput(attrs={'class': 'form-control'}),
            'standort': forms.Select(attrs={'class': 'form-control'}),
            'eintrittsdatum': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'aktiv': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def clean_personalnummer(self):
        personalnummer = self.cleaned_data.get('personalnummer')
        
        # Prüfe auf Duplikate
        existing = Mitarbeiter.objects.filter(
            personalnummer=personalnummer
        ).exclude(pk=self.instance.pk if self.instance else None)
        
        if existing.exists():
            raise ValidationError('Diese Personalnummer existiert bereits.')
        
        return personalnummer


class GenehmigungForm(forms.Form):
    """Formular für Genehmigung/Ablehnung von Vereinbarungen"""
    
    AKTION_CHOICES = [
        ('genehmigen', 'Genehmigen'),
        ('ablehnen', 'Ablehnen'),
        ('aktivieren', 'Aktivieren'),
    ]
    
    aktion = forms.ChoiceField(
        choices=AKTION_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='Aktion'
    )
    
    bemerkung = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 4,
            'class': 'form-control',
            'placeholder': 'Optional: Bemerkung zur Entscheidung'
        }),
        label='Bemerkung'
    )


class FilterForm(forms.Form):
    """Formular für Filter in Listen"""
    
    status = forms.ChoiceField(
        choices=[('', 'Alle')] + list(Arbeitszeitvereinbarung.STATUS_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Status'
    )
    
    abteilung = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Abteilung'
        }),
        label='Abteilung'
    )
    
    standort = forms.ChoiceField(
        choices=[('', 'Alle')] + list(Mitarbeiter.STANDORT_CHOICES),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Standort'
    )
    
    jahr = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '2020',
            'max': '2050',
            'placeholder': timezone.now().year
        }),
        label='Jahr'
    )
    
    monat = forms.IntegerField(
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1',
            'max': '12',
            'placeholder': timezone.now().month
        }),
        label='Monat'
    )
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password



class RegisterForm(forms.Form):
    username = forms.CharField(label="Benutzername", max_length=150)
    email = forms.EmailField(label="E-Mail")

    vorname = forms.CharField(label="Vorname", max_length=100)
    nachname = forms.CharField(label="Nachname", max_length=100)

    personalnummer = forms.CharField(label="Personalnummer", max_length=20)
    abteilung = forms.CharField(label="Abteilung", max_length=100)
    standort = forms.ChoiceField(choices=Mitarbeiter.STANDORT_CHOICES)
    eintrittsdatum = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    password1 = forms.CharField(widget=forms.PasswordInput, label="Passwort")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Passwort bestätigen")

    def clean_username(self):
        if User.objects.filter(username=self.cleaned_data['username']).exists():
            raise ValidationError("Benutzername existiert bereits.")
        return self.cleaned_data['username']

    def clean_personalnummer(self):
        if Mitarbeiter.objects.filter(personalnummer=self.cleaned_data['personalnummer']).exists():
            raise ValidationError("Personalnummer existiert bereits.")
        return self.cleaned_data['personalnummer']

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('password1') != cleaned.get('password2'):
            raise ValidationError("Passwörter stimmen nicht überein.")
        validate_password(cleaned.get('password1'))
        return cleaned