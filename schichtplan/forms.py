"""
Forms für Schichtplan-App
"""
from django import forms
from .models import Schichtplan, Schicht


class ExcelImportForm(forms.Form):
    """Form für Excel-Upload"""
    
    excel_file = forms.FileField(
        label='Excel-Datei auswählen',
        help_text='Schichtplan im Excel-Format (.xlsx)',
        widget=forms.FileInput(attrs={
            'accept': '.xlsx,.xls',
            'class': 'form-control',
        })
    )
    
    def clean_excel_file(self):
        """Validierung"""
        file = self.cleaned_data.get('excel_file')
        
        if not file:
            raise forms.ValidationError('Keine Datei ausgewählt')
        
        # Max 5MB
        if file.size > 5 * 1024 * 1024:
            raise forms.ValidationError('Datei zu groß (max. 5MB)')
        
        # Nur Excel
        if not file.name.endswith(('.xlsx', '.xls')):
            raise forms.ValidationError('Nur Excel-Dateien erlaubt')
        
        return file
class SchichtplanForm(forms.ModelForm):
    class Meta:
        model = Schichtplan
        fields = '__all__'  # oder spezifische Felder


class SchichtForm(forms.ModelForm):
    class Meta:
        model = Schicht
        fields = '__all__'  # oder spezifische Felder