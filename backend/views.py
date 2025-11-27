from django.shortcuts import render
from distutils.util import strtobool
from rest_framework.request import Request
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import IntegrityError
from django.db.models import Q, Sum, F
from django.http import JsonResponse
from requests import get
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from ujson import loads as load_json
from yaml import load as load_yaml, Loader
from django.utils import timezone
from datetime import timedelta

from backend.models import Shop, Category, Product, ProductInfo, Parameter, ProductParameter, Order, OrderItem, \
    Contact, ConfirmEmailToken
from backend.serializers import UserSerializer, CategorySerializer, ShopSerializer, ProductInfoSerializer, \
    OrderItemSerializer, OrderSerializer, ContactSerializer
from backend.signals import new_user_registered, new_order

# Create your views here.
class PartnerUpdate(APIView):
    """
    A class for updating partner information.

    Methods:
    - post: Update the partner information.

    Attributes:
    - None
    """

    def post(self, request, *args, **kwargs):
        """
                Update the partner price list information.

                Args:
                - request (Request): The Django request object.

                Returns:
                - JsonResponse: The response indicating the status of the operation and any errors.
                """
        # Аутентинтификация
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)

        url = request.data.get('url')
        # Валидация URL
        if url:
            validate_url = URLValidator()
            try:
                validate_url(url)
            except ValidationError as e:
                return JsonResponse({'Status': False, 'Error': str(e)})
            else:
                # Загрузка YAML

                try:
                    stream = get(url, timeout=20).content
                    data = load_yaml(stream, Loader=Loader)
                except Exception as e:
                    return JsonResponse({'Status': False, 'Error': f'Ошибка загрузки файла: {str(e)}'})
                
                required_fields = ['shop', 'categories', 'goods']
                for field in required_fields:
                    if field not in data:
                        return JsonResponse({
                            'Status': False, 
                            'Error': f'Отсутствует обязательное поле: {field}'
                        }, status=400)
                # stream = get(url).content
                # data = load_yaml(stream, Loader=Loader)

                # Импорт магазина
                shop, _ = Shop.objects.get_or_create(name=data['shop'], user_id=request.user.id)
                # Импорт категорий магазина
                for category in data['categories']:
                    category_object, _ = Category.objects.get_or_create(id=category['id'], name=category['name'])
                    category_object.shops.add(shop.id)
                    category_object.save()
                #Удаляем все предыдущие предложения товаров этого магазина перед новым импортом
                ProductInfo.objects.filter(shop_id=shop.id).delete()
                # Импорт товаров
                for item in data['goods']:
                    product, _ = Product.objects.get_or_create(name=item['name'], category_id=item['category'])

                    product_info = ProductInfo.objects.create(product_id=product.id,
                                                              external_id=item['id'],
                                                              model=item['model'],
                                                              price=item['price'],
                                                              price_rrc=item['price_rrc'],
                                                              quantity=item['quantity'],
                                                              shop_id=shop.id)
                    # Обработка параметров товаров
                    for name, value in item['parameters'].items():
                        parameter_object, _ = Parameter.objects.get_or_create(name=name)
                        ProductParameter.objects.create(product_info_id=product_info.id,
                                                        parameter_id=parameter_object.id,
                                                        value=value)

                return JsonResponse({'Status': True})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'})
    

from django.http import JsonResponse
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from rest_framework.views import APIView
from .models import User, ConfirmEmailToken
from .serializers import UserSerializer


class RegisterAccount(APIView):
    """
    Класс для регистрации покупателей
    """

    def post(self, request, *args, **kwargs):
        """
        Process a POST request and create a new user.
        """
        # Проверяем обязательные аргументы
        if {'first_name', 'last_name', 'email', 'password', 'company', 'position'}.issubset(request.data):

            # Проверяем пароль на сложность
            try:
                validate_password(request.data['password'])
            except ValidationError as password_error:  
                error_array = []
                for item in password_error:
                    error_array.append(item)
                return JsonResponse({'Status': False, 'Errors': {'password': error_array}})
            else:
                # Проверяем, существует ли пользователь
                if User.objects.filter(email=request.data['email']).exists():
                    return JsonResponse({
                        'Status': False, 
                        'Errors': 'Пользователь с таким email уже существует'
                    })

                user_serializer = UserSerializer(data=request.data)
                if user_serializer.is_valid():
                    # Сохраняем пользователя
                    user = user_serializer.save()
                    user.set_password(request.data['password'])
                    user.is_active = False  

                    # Создаем токен подтверждения
                    token = ConfirmEmailToken.objects.create(user=user)
                    
                    # Отправляем email 
                    self._send_confirmation_email(user.email, token.key)
                    
                    return JsonResponse({'Status': True})
                else:
                    return JsonResponse({'Status': False, 'Errors': user_serializer.errors})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'})

    def _send_confirmation_email(self, email, token):
        """
        Заглушка для отправки email 
        """
        print(f"Confirmation email to: {email}")
        print(f"Token: {token}")
        # TODO: Реальная отправка email
        # send_mail(...)


class ConfirmAccount(APIView):
    """
    Класс для подтверждения почтового адреса
    """

    def post(self, request, *args, **kwargs):
        """
        Подтверждает почтовый адрес пользователя.
        """
        if {'email', 'token'}.issubset(request.data):
            token = ConfirmEmailToken.objects.filter(
                user__email=request.data['email'],
                key=request.data['token']
            ).first()
            
            if token:
                # Проверяем срок действия токена 
                token_age = timezone.now() - token.created_at
                if token_age > timedelta(hours=24):
                    token.delete()
                    return JsonResponse({
                        'Status': False, 
                        'Errors': 'Срок действия токена истек'
                    })
                
                token.user.is_active = True
                token.user.save()
                token.delete()
                return JsonResponse({'Status': True})
            else:
                return JsonResponse({
                    'Status': False, 
                    'Errors': 'Неправильно указан токен или email'
                })

        return JsonResponse({
            'Status': False, 
            'Errors': 'Не указаны все необходимые аргументы'
        })


class AccountDetails(APIView):
    """
    Класс для управления данными пользовательского аккаунта
    """

    def get(self, request: Request, *args, **kwargs):
        """
        Получение данных текущего пользователя
        """
        if not request.user.is_authenticated:
            return JsonResponse(
                {'Status': False, 'Error': 'Требуется авторизация'}, 
                status=403
            )

        serializer = UserSerializer(request.user)
        return Response(serializer.data)

    def post(self, request: Request, *args, **kwargs):
        """
        Обновление данных пользователя
        """
        if not request.user.is_authenticated:
            return JsonResponse(
                {'Status': False, 'Error': 'Требуется авторизация'}, 
                status=403
            )

        errors = {}
        
        # Обработка смены пароля
        if 'password' in request.data:
            try:
                validate_password(request.data['password'])
                request.user.set_password(request.data['password'])
            except ValidationError as password_error:  
                errors['password'] = list(password_error)
        
        # Обработка смены email 
        if 'email' in request.data and request.data['email'] != request.user.email:
            if User.objects.filter(email=request.data['email']).exists():
                errors['email'] = ['Пользователь с таким email уже существует']

        if errors:
            return JsonResponse(
                {'Status': False, 'Errors': errors}, 
                status=400
            )

        # Обновление остальных данных
        user_serializer = UserSerializer(
            request.user, 
            data=request.data, 
            partial=True
        )
        
        if user_serializer.is_valid():
            user_serializer.save()
            
            if 'password' in request.data:
                request.user.save()
            
            return JsonResponse({'Status': True})
        else:
            return JsonResponse(
                {'Status': False, 'Errors': user_serializer.errors}, 
                status=400
            )
        

class LoginAccount(APIView):
    """
    Класс для авторизации пользователей
    """

    def post(self, request, *args, **kwargs):
        """
        Аутентификация пользователя
        """
        # Проверяем обязательные аргументы
        if not {'email', 'password'}.issubset(request.data):
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны email или пароль'},
                status=400
            )

        email = request.data['email'].strip().lower()
        password = request.data['password']

        # Аутентификация пользователя
        user = authenticate(request, username=email, password=password)

        if user is not None:
            if user.is_active:
                # Создаем или получаем токен
                token, created = Token.objects.get_or_create(user=user)
                # Обновляем время последнего входа
                user.last_login = timezone.now()
                user.save(update_fields=['last_login'])
                
                response_data = {
                    'Status': True, 
                    'Token': token.key,
                    'User': {
                        'id': user.id,
                        'email': user.email,
                        'first_name': user.first_name,
                        'last_name': user.last_name,
                        'company': user.company,
                        'position': user.position,
                        'type': user.type
                    }
                }
                
                return JsonResponse(response_data)
            else:
                return JsonResponse(
                    {'Status': False, 'Errors': 'Аккаунт не активирован. Проверьте email для подтверждения.'},
                    status=403
                )
        else:
            error_message = self._get_auth_error_message(email)
            return JsonResponse(
                {'Status': False, 'Errors': error_message},
                status=401
            )

    def _get_auth_error_message(self, email):
        """
        Определяем причину ошибки аутентификации
        """
        try:
            user = User.objects.get(email=email)
            if not user.is_active:
                return 'Аккаунт не активирован. Проверьте email для подтверждения.'
            else:
                return 'Неверный пароль'
        except User.DoesNotExist:
            return 'Пользователь с таким email не найден'