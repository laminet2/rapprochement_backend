from django.urls import path
from .views import ImportValorixView,ImportValorixJSONView

urlpatterns = [
    path('',ImportValorixView.as_view()),
    path('save/',ImportValorixJSONView.as_view())
]
