from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.contrib.auth import get_user_model

User = get_user_model()

@shared_task
def send_new_order_email_task(user_id, order_id=None):
    """
    Асинхронная отправка письма о новом заказе
    """
    try:
        user = User.objects.get(id=user_id)
        
        body = f"""
        Здравствуйте, {user.first_name} {user.last_name}!
        
        Ваш заказ успешно оформлен и принят в работу.
        
        Спасибо за покупку!
        """
        
        msg = EmailMultiAlternatives(
            subject=f"Ваш заказ № {order_id} оформлен",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email]
        )
        msg.send()
        
        return f"Письмо о заказе #{order_id} отправлено на {user.email}"
        
    except Exception as e:
        return f"Ошибка отправки письма пользователю #{user_id}: {str(e)}"
    

@shared_task
def send_password_reset_email_task(user_email, token_key, username):
    """Асинхронная отправка токена для сброса пароля"""
    try:
        msg = EmailMultiAlternatives(
            subject=f"Password Reset Token for {username}",
            message=token_key,
            from_email=settings.EMAIL_HOST_USER,
            to=[user_email]
        )
        msg.send()
        
        return f"Токен сброса пароля отправлен на {user_email}"
        
    except Exception as e:
        return f"Ошибка отправки токена сброса пароля: {str(e)}"


@shared_task
def send_registration_confirmation_email_task(user_id, token_key):
    """Асинхронная отправка письма с подтверждением регистрации"""
    try:
        user = User.objects.get(id=user_id)
        
        body = f"""
        Здравствуйте, {user.first_name} {user.last_name}!
        
        Для подтверждения регистрации используйте следующий токен:
        
        {token_key}
        
        Отправьте POST запрос на /api/v1/user/register/confirm с параметрами:
        - email: {user.email}
        - token: {token_key}
        
        Если вы не регистрировались, проигнорируйте это письмо.
        """
        
        msg = EmailMultiAlternatives(
            subject="Подтверждение регистрации в интернет магазине",
            body=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email]
        )
        msg.send()
        
        return f"Письмо подтверждения отправлено на {user.email}"
        
    except Exception as e:
        return f"Ошибка отправки письма подтверждения: {str(e)}"


@shared_task
def send_order_status_changed_email_task(order_id, user_id, old_status, new_status):
    """Асинхронное уведомление об изменении статуса заказа"""
    try:
        from backend.models import Order
        
        user = User.objects.get(id=user_id)
        order = Order.objects.get(id=order_id)
        
        body = f"""
        Здравствуйте, {user.first_name} {user.last_name}!
        
        Статус вашего заказа №{order_id} изменен.
        
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
        
        return f"Уведомление о статусе заказа #{order_id} отправлено"
        
    except Exception as e:
        return f"Ошибка отправки уведомления о статусе: {str(e)}"

  
@shared_task
def send_order_item_quantity_changed_email_task(order_id, user_id, changes):
    """Асинхронное уведомление об изменении состава заказа"""
    try:
        user = User.objects.get(id=user_id)
        
        # Группируем изменения по типу
        removed_items = [c for c in changes if c.get('action') == 'removed']
        updated_items = [c for c in changes if c.get('action') == 'updated']
        
        message_text = []
        
        if removed_items:
            message_text.append("\nУдаленные товары:") 
            for item in removed_items:
                message_text.append(f"  - {item.get('product_name', 'Товар')}: {item.get('old_quantity', 0)} шт.")
        
        if updated_items:
            if removed_items:
                message_text.append("")  
            message_text.append("Измененные количества товаров:")
            for item in updated_items:
                message_text.append(f"  - {item.get('product_name', 'Товар')}: {item.get('old_quantity', 0)} → {item.get('new_quantity', 0)} шт.")
        
        if not message_text:
            return "Нет изменений для уведомления"
        
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
        
        return f"Уведомление об изменении {len(changes)} товаров отправлено на {user.email}"
        
    except Exception as e:
        return f"Ошибка отправки уведомления: {str(e)}"