from django.contrib import admin
from .models import Schichttyp, Schichtplan, Schicht, Schichtwunsch, Schichttausch


@admin.register(Schichttyp)
class SchichttypAdmin(admin.ModelAdmin):
    list_display = ['name', 'kuerzel', 'start_zeit', 'ende_zeit', 'aktiv']


@admin.register(Schichtplan)
class SchichtplanAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_datum', 'ende_datum', 'status']


@admin.register(Schicht)
class SchichtAdmin(admin.ModelAdmin):
    list_display = ['mitarbeiter', 'datum', 'schichttyp']


@admin.register(Schichtwunsch)
class SchichtwunschAdmin(admin.ModelAdmin):
    list_display = ['mitarbeiter', 'datum']


@admin.register(Schichttausch)
class SchichttauschAdmin(admin.ModelAdmin):
    list_display = ['urspruengliche_schicht', 'status']