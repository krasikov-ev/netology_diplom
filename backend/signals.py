from typing import Type

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models.signals import post_save
from django.dispatch import receiver, Signal
from django_rest_passwordreset.signals import reset_password_token_created

from backend.models import ConfirmEmailToken, User

new_user_registered = Signal()

new_order = Signal()


@receiver(reset_password_token_created)
def password_reset_token_created(sender, instance, reset_password_token, **kwargs):
    """
    Отправляем письмо с токеном для сброса пароля
    When a token is created, an e-mail needs to be sent to the user
    :param sender: View Class that sent the signal
    :param instance: View Instance that sent the signal
    :param reset_password_token: Token Model Object
    :param kwargs:
    :return:
    """
    # send an e-mail to the user

    msg = EmailMultiAlternatives(
        # title:
        f"Password Reset Token for {reset_password_token.user}",
        # message:
        reset_password_token.key,
        # from:
        settings.EMAIL_HOST_USER,
        # to:
        [reset_password_token.user.email]
    )
    msg.send()


# @receiver(post_save, sender=User)
# def new_user_registered_signal(sender: Type[User], instance: User, created: bool, **kwargs):
#     """
#      отправляем письмо с подтрердждением почты
#     """
#     if created and not instance.is_active:
#         # send an e-mail to the user
#         token, _ = ConfirmEmailToken.objects.get_or_create(user_id=instance.pk)

#         msg = EmailMultiAlternatives(
#             # title:
#             f"Password Reset Token for {instance.email}",
#             # message:
#             token.key,
#             # from:
#             settings.EMAIL_HOST_USER,
#             # to:
#             [instance.email]
#         )
#         msg.send()
@receiver(post_save, sender=User)
def new_user_registered_signal(sender: Type[User], instance: User, created: bool, **kwargs):
    """
    Отправляем письмо с подтверждением почты (режим разработки)
    """
    if created and not instance.is_active:
        try:
            # Создаем или получаем токен
            token, _ = ConfirmEmailToken.objects.get_or_create(user_id=instance.pk)
            
            # Логируем (вместо реальной отправки в DEV режиме)
            print(f"✅ [DEV MODE] Пользователь {instance.email} зарегистрирован")
            print(f"📧 [DEV MODE] Токен подтверждения: {token.key}")
            print(f"📧 [DEV MODE] Письмо было бы отправлено в продакшене")
            print(f"📧 [DEV MODE] Для активации перейдите по ссылке: /api/v1/user/register/confirm/?token={token.key}")
            
            # В режиме разработки НЕ отправляем реальное письмо
            # Если нужно тестировать отправку, раскомментируйте ниже
            
            # msg = EmailMultiAlternatives(
            #     f"Password Reset Token for {instance.email}",
            #     token.key,
            #     settings.EMAIL_HOST_USER,
            #     [instance.email]
            # )
            # msg.send()  # В режиме console.EmailBackend покажет письмо в терминале
            
        except Exception as e:
            print(f"⚠️  Ошибка в сигнале регистрации: {e}")
            # НЕ ПОДНИМАЕМ ИСКЛЮЧЕНИЕ - пользователь уже создан

@receiver(new_order)
def new_order_signal(user_id, **kwargs):
    """
    отправяем письмо при изменении статуса заказа
    """
    # send an e-mail to the user
    user = User.objects.get(id=user_id)

    msg = EmailMultiAlternatives(
        # title:
        f"Обновление статуса заказа",
        # message:
        'Заказ сформирован',
        # from:
        settings.EMAIL_HOST_USER,
        # to:
        [user.email]
    )
    msg.send()