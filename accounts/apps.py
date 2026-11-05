from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = 'accounts'

    def ready(self):
        from django.contrib.auth.models import update_last_login
        from django.contrib.auth.signals import user_logged_in

        user_logged_in.disconnect(update_last_login, dispatch_uid="update_last_login")
