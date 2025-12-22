from typing import Type

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db.models.signals import post_save
from django.dispatch import receiver, Signal
from django_rest_passwordreset.signals import reset_password_token_created

from backend.models import ConfirmEmailToken, User, Order

new_user_registered = Signal()
new_order = Signal()
order_status_changed = Signal()
order_item_quantity_changed = Signal()

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


@receiver(post_save, sender=User)
def new_user_registered_signal(sender, instance: User, created: bool, **kwargs):
    """
    Отправляем письмо с подтверждением регистрации
    """
    if created and not instance.is_active:
        try:
            token, _ = ConfirmEmailToken.objects.get_or_create(user_id=instance.pk)
            body=f"""
                Здравствуйте, {instance.first_name} {instance.last_name}!
                
                Для подтверждения регистрации используйте следующий токен:
                
                {token.key}
                
                Отправьте POST запрос на /api/v1/user/register/confirm с параметрами:
                - email: {instance.email}
                - token: {token.key}
                
                Если вы не регистрировались, проигнорируйте это письмо.
            
                """
            print (f"Для тестирования: {token.key}")
            msg = EmailMultiAlternatives(
                subject="Подтверждение регистрации в интернет магазине",
                body=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[instance.email]
            )
            msg.send()
        except Exception as e:
            print(f"Failed to send confirmation email to {instance.email}: {e}")


# @receiver(post_save, sender=User)
# def new_user_registered_signal(sender: Type[User], instance: User, created: bool, **kwargs):
#     """
#     Эмулирует отправку  письма с подтверждением почты 
#     """
#     if created and not instance.is_active:
#         try:
#             # Создаем или получаем токен
#             token, _ = ConfirmEmailToken.objects.get_or_create(user_id=instance.pk)
            
#             # Логируем (вместо реальной отправки в DEV режиме)
#             print(f"Пользователь {instance.email} зарегистрирован")
#             print(f"Токен подтверждения: {token.key}")       


@receiver(new_order)
def new_order_signal(user_id, **kwargs):
    """
    Отправляем письмо при создании нового заказа
    """
    try:
        user = User.objects.get(id=user_id)
        order_id = kwargs.get('order_id', '')
        body=f"""
            Здравствуйте, {user.first_name} {user.last_name}!
            
            Ваш заказ успешно оформлен и принят в обработку.
            
            Спасибо за покупку!
            """
        msg = EmailMultiAlternatives(
            subject=f"Ваш заказ № {order_id} оформлен",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email]
        )
        msg.send()
    
        
    except Exception as e:
        print(f"Failed to send new order email to user #{user_id}: {e}")


@receiver(order_status_changed)
def order_status_changed_signal(order_id, user_id, old_status, new_status, **kwargs): 
    """
    Уведомление ою изменении статуса заказа
    """
    try:
        user = User.objects.get(id=user_id)
        order = Order.objects.get(id=order_id)

        body = f"""
        Здравствуйте, {user.first_name} {user.last_name}!
        
        Статус вашего заказа №{order_id} изменен".
        
        Детали заказа:
        - Номер: {order_id}
        - Новый статус: {order.get_state_display()}
        - Дата изменения: {order.updated_at.strftime('%d.%m.%Y %H:%M')}
        
        С уважением,
        магазин.
        """

        msg = EmailMultiAlternatives(
            subject=f"Статус заказа #{order_id} обновлен",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email]
        )
        msg.send()
        
    except Exception as e:
        print(f"Ошибка отправки уведомления о статусе: {e}")


@receiver(order_item_quantity_changed)
def order_item_quantity_changed_signal(order_id, user_id, changes, **kwargs):
    """
    Уведомление об изменении состава заказа 
    """
    try:
        user = User.objects.get(id=user_id)
        
        # Группируем изменения по типу
        removed_items = [c for c in changes if c['action'] == 'removed']
        updated_items = [c for c in changes if c['action'] == 'updated']
        
        # Формируем сообщение
        message_text = []
        
        if removed_items:
            message_text.append("")  
            message_text.append("Удаленные товары:")
            for item in removed_items:
                message_text.append(f"  - {item['product_name']}: {item['old_quantity']} шт.")
        
        if updated_items:
            if removed_items:  
                message_text.append("")
            message_text.append("Измененные количества товаров:")
            for item in updated_items:
                message_text.append(f"  - {item['product_name']}: {item['old_quantity']} → {item['new_quantity']} шт.")
        
        if not message_text:
            return  
        
        body = f"""
        Здравствуйте, {user.first_name} {user.last_name}!
        
        Состав вашего заказа #{order_id} был изменен.
        
        {"".join(message_text)}
        
        Если у вас есть вопросы, свяжитесь с магазином.
        """
        
        msg = EmailMultiAlternatives(
            subject=f"Изменение состава заказа #{order_id}",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email]
        )
        msg.send()
        
        # print(f"Уведомление об изменении {len(changes)} товаров отправлено на {user.email}")
        
    except Exception as e:
        print(f"Ошибка отправки уведомления о составе: {e}")