from django.urls import path
from . import views

app_name = 'schichtplan'

urlpatterns = [
    # Dashboard
    path('', views.planer_dashboard, name='dashboard'),
    
    # Schichtplan
    path('erstellen/', views.schichtplan_erstellen, name='erstellen'),
    path('<int:pk>/', views.schichtplan_detail, name='detail'),
    
    # Excel-Import
    path('<int:pk>/import/', views.excel_import_view, name='excel_import'),
    path('import/analyse/', views.excel_analyse_view, name='excel_analyse'),
    
    # Mitarbeiter
    path('mitarbeiter/', views.mitarbeiter_uebersicht, name='mitarbeiter_uebersicht'),
    
    # Schichten
    path('<int:schichtplan_pk>/schicht-zuweisen/', views.schicht_zuweisen, name='schicht_zuweisen'),
    path('schicht/<int:pk>/loeschen/', views.schicht_loeschen, name='schicht_loeschen'),
    path('wuensche/periode/<int:periode_id>/genehmigen/', 
         views.wuensche_genehmigen, 
         name='wuensche_genehmigen'),
]