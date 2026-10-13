from django.urls import path
from .views import ImportValorixView

urlpatterns = [
    path('',ImportValorixView.as_view())
]
