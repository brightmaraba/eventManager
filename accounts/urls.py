from django.urls import path

from accounts import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("mfa/enroll/", views.mfa_enroll, name="mfa-enroll"),
    path("mfa/verify/", views.mfa_verify, name="mfa-verify"),
    path("password-reset/", views.PasswordResetView.as_view(template_name="accounts/password_reset.html", email_template_name="accounts/password_reset_email.txt", success_url="/accounts/password-reset/done/"), name="password-reset"),
    path("password-reset/done/", views.PasswordResetDoneView.as_view(template_name="accounts/password_reset_done.html"), name="password-reset-done"),
    path("reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(template_name="accounts/password_reset_confirm.html", success_url="/accounts/reset/done/"), name="password-reset-confirm"),
    path("reset/done/", views.PasswordResetCompleteView.as_view(template_name="accounts/password_reset_complete.html"), name="password-reset-complete"),
    path("organizations/", views.organization_select, name="organization-select"),
    path("members/", views.members, name="members"),
]
