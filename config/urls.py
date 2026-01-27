from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Authentication
    path('accounts/login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('accounts/logout/', auth_views.LogoutView.as_view(next_page='/'), name='logout'),  # ← next_page hinzugefügt!
    path('accounts/', include('django.contrib.auth.urls')),
    
    # APPS
    path('', include('arbeitszeit.urls')),
    path('schichtplan/', include('schichtplan.urls')),
]