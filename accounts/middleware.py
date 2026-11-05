import time
from django.conf import settings
from django.contrib.auth import logout
from django.contrib.sessions.exceptions import SessionInterrupted
from django.shortcuts import redirect


class SessionInterruptedMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        except SessionInterrupted:
            return redirect("login")


class AutoLogoutMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):

        if request.user.is_authenticated:

            current_time = int(time.time())
            last_activity = request.session.get('last_activity', current_time)

            if current_time - last_activity > settings.SESSION_COOKIE_AGE:

                was_superuser = request.user.is_superuser
                logout(request)

                if was_superuser:
                    return redirect("home")
                return redirect("login")

            request.session['last_activity'] = current_time

        response = self.get_response(request)

        return response
