"""Login by username, email, phone number, or national-ID number.

The old alfaqihcars site let users sign in with any of their email, Saudi
phone (05XXXXXXXX) or identity number. Those extra identifiers are carried
into the tenant as UserProfile.phone / UserProfile.identity_number, and this
backend resolves whichever one was typed in the login form's "username" box.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class MultiIdentifierBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or password is None:
            return None
        ident = username.strip()
        user = self._find(ident)
        if user is None:
            # Run the default hasher anyway to keep timing uniform.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def _find(self, ident):
        # username / email are on the user table; phone / id live on the profile.
        qs = User.objects.filter(username__iexact=ident).first()
        if qs:
            return qs
        if "@" in ident:
            u = User.objects.filter(email__iexact=ident).first()
            if u:
                return u
        from .models import UserProfile
        prof = (UserProfile.objects.filter(phone=ident).select_related("user").first()
                or UserProfile.objects.filter(identity_number=ident).select_related("user").first())
        return prof.user if prof else None
