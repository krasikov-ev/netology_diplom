# from django.shortcuts import render
# from django.db import transaction
# # from distutils.util import strtobool
# import yaml
# from django.http import HttpResponse
# from django.utils import timezone
# from setuptools._distutils.util import strtobool
# from rest_framework.request import Request
# from django.contrib.auth import authenticate
# from django.contrib.auth.password_validation import validate_password
# from django.core.exceptions import ValidationError
# from django.core.validators import URLValidator
# from django.db import IntegrityError
# from django.db.models import Q, Sum, F
# from django.http import JsonResponse
# from requests import get
# from rest_framework.authtoken.models import Token
# from rest_framework.generics import ListAPIView
# from rest_framework.response import Response
# from rest_framework.views import APIView
# from django.dispatch import receiver
# from rest_framework.permissions import IsAuthenticated
# from rest_framework.authentication import TokenAuthentication, SessionAuthentication
# from ujson import loads as load_json
# from yaml import load as load_yaml, Loader
# from django.utils import timezone
# from datetime import timedelta
# from rest_framework.pagination import PageNumberPagination
# from .models import User, USER_TYPE_CHOICES
# # from orders.settings import DEFAULT_FROM_EMAIL
# from django.core.mail import send_mail
# from django.conf import settings


# from backend.models import Shop, Category, Product, ProductInfo, Parameter, ProductParameter, Order, OrderItem, \
#     Contact, ConfirmEmailToken
# from backend.serializers import UserSerializer, CategorySerializer, ShopSerializer, ProductInfoSerializer, \
#     OrderItemSerializer, OrderSerializer, ContactSerializer, PartnerOrderItemUpdateSerializer, PartnerOrderStatusSerializer
# from backend.signals import  new_order, order_status_changed, order_item_quantity_changed



import yaml
from datetime import timedelta


from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum, F
from django.dispatch import receiver
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination


import requests
from ujson import loads as load_json
from yaml import load as load_yaml, Loader
from setuptools._distutils.util import strtobool

# Локальные импорты
from backend.models import (
    User, USER_TYPE_CHOICES,
    Shop, Category, Product, ProductInfo, 
    Parameter, ProductParameter, Order, OrderItem,
    Contact, ConfirmEmailToken
)
from backend.serializers import (
    UserSerializer, CategorySerializer, ShopSerializer, 
    ProductInfoSerializer, OrderItemSerializer, OrderSerializer,
    ContactSerializer, PartnerOrderItemUpdateSerializer,
    PartnerOrderStatusSerializer
)
from backend.signals import new_order, order_status_changed, order_item_quantity_changed


class PartnerUpdate(APIView):
    """
    Класс для обновления информации  поставщика
    """

    def post(self, request, *args, **kwargs):
        """
        Импорт прайс-листа поставщика из YAML файла по URL
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


class PartnerExport(APIView):
    """
    Класс для экспорта прайс-листа магазина
    """
    def get(self, request, *args, **kwargs):
        pass
        # Аутентинтификация
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)

        try:
            # Проверка если еще не создан магазин (не было импорта)
            shop = Shop.objects.filter(user_id=request.user.id).first()
            if not shop:
                return JsonResponse({'Status': False, 'Error': 'Магазин не найден'}, status=404)
            
            # Собираем данные в структуру для YAML
            export_data = {
                'shop': shop.name,
                'categories': [],
                'goods': []
            }
            
            # Собираем категории
            categories = Category.objects.filter(shops=shop).distinct()
            for category in categories:
                export_data['categories'].append({
                    'id': category.id,
                    'name': category.name
                })
            
            # Собираем товары
            products = ProductInfo.objects.filter(
                shop=shop
            ).select_related('product', 'product__category').prefetch_related('product_parameters__parameter')
            
            for product in products:
                product_data = {
                    'id': product.external_id,                    
                    'category': product.product.category_id,
                    'model': product.model,
                    'name': product.product.name,
                    'price': float(product.price) if product.price is not None else None,
                    'price_rrc': float(product.price_rrc) if product.price is not None else None,
                    'quantity': product.quantity,
                    'parameters': {}
                }
                
                # Добавляем параметры товара
                for param in product.product_parameters.all():
                    product_data['parameters'][param.parameter.name] = param.value
                
                export_data['goods'].append(product_data)
            
            # Формируем YAML
            yaml_data = yaml.dump(
                export_data,
                allow_unicode=True,  
                default_flow_style=False,  
                sort_keys=False  
            )

            # вставляем пустую строку
            if '\ngoods:' in yaml_data:
                goods_index = yaml_data.find('\ngoods:')
                yaml_data = yaml_data[:goods_index] + '\n' + yaml_data[goods_index:]

            # Создаем HTTP-ответ с YAML файлом
            response = HttpResponse(yaml_data, content_type='application/x-yaml')
            response['Content-Disposition'] = f'attachment; filename="{shop.name}_export_{timezone.now().date()}.yaml"'
            return response
            
        except Exception as e:
            return JsonResponse({
                'Status': False, 
                'Error': f'Ошибка при экспорте: {str(e)}'
            }, status=500)


class RegisterAccount(APIView):
    """
    Класс для регистрации пользователей
    """

    def post(self, request, *args, **kwargs):
        """
        Создание пользователя методом POST
        """
        # Проверяем обязательные аргументы
        if {'first_name', 'last_name', 'email', 'password', 'company', 'position'}.issubset(request.data):


            # Проверяем тип пользователя 
            user_type = request.data.get('type', 'buyer') 
            valid_types = dict(USER_TYPE_CHOICES).keys()
            
            if user_type not in valid_types:
                return JsonResponse({
                    'Status': False, 
                    'Errors': f'Недопустимый тип пользователя. Допустимо: {", ".join(valid_types)}'
                }, status=400)
            # Проверяем пароль на сложность
            try:
                validate_password(request.data['password'])
            except ValidationError as password_error:  
                error_array = []
                for item in password_error:
                    error_array.append(item)
                return JsonResponse({'Status': False, 'Errors': {'password': error_array}}, status = 400)
            else:
                # Проверяем, существует ли пользователь
                if User.objects.filter(email=request.data['email']).exists():
                    return JsonResponse({
                        'Status': False, 
                        'Errors': 'Пользователь с таким email уже существует'
                    },
                    status=400)
               
                user_serializer = UserSerializer(data=request.data)
                if user_serializer.is_valid():
                    # Сохраняем пользователя
                    user = user_serializer.save()
                    user.set_password(request.data['password'])
                    user.is_active = False  
                    user.type = user_type
                    user.save()

                    # Создаем токен подтверждения
                    # token = ConfirmEmailToken.objects.create(user=user)
                
                    # self._send_confirmation_email(user, token.key)
                    
                    return JsonResponse({'Status': True})
                else:
                    return JsonResponse({'Status': False, 'Errors': user_serializer.errors})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}, status = 400)

 
    # def _send_confirmation_email(self, user, token):
    #     """
    #     Отправка email
    #     """
    #     subject = 'Подтверждение регистрации в интернет магазине'
        
    #     message = f"""
    #     Здравствуйте, {user.first_name} {user.last_name}!
        
    #     Для подтверждения регистрации используйте следующий токен:
        
    #     {token}
        
    #     Отправьте POST запрос на /api/v1/user/register/confirm с параметрами:
    #     - email: {user.email}
    #     - token: {token}
       
    #     """
        
    #     try:
    #         send_mail(
    #             subject=subject,
    #             message=message.strip(),  
    #             from_email=settings.DEFAULT_FROM_EMAIL,
    #             recipient_list=[user.email],
    #         )
    #         # print(f"email отправлен на: {user.email}")
    #     except Exception as e:
    #         print(f"Failed to send email to {user.email}: {str(e)}")


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

                 # СОЗДАЕМ АВТОРИЗАЦИОННЫЙ ТОКЕН API
                # from rest_framework.authtoken.models import Token
                # api_token, created = Token.objects.get_or_create(user=token.user)

                token.delete()
                return JsonResponse({
                    'Status': True,
                    # 'Token': api_token.key 
                    })
            else:
                return JsonResponse({
                    'Status': False,'Errors': 'Неправильно указан токен или email'
                    },
                    status=400
                    )

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

        # email = request.data['email'].strip().lower()
        email = request.data['email'].strip()
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
        

class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class CategoryView(ListAPIView):
    """
    Класс для просмотра категорий
    """
    queryset = Category.objects.all().order_by('name') 
    serializer_class = CategorySerializer
    pagination_class = StandardPagination 


class ShopView(ListAPIView):
    """
    Класс для просмотра списка магазинов
    """
    queryset = Shop.objects.filter(state=True).order_by('name')
    serializer_class = ShopSerializer


class ProductInfoView(APIView):
    """
    Класс для поиска и фильтрации товаров
    """
    def get(self, request: Request, *args, **kwargs):
        """
        Поиск товаров с фильтрацией по  параметрам
        """
        query = Q(shop__state=True)
        shop_id = request.query_params.get('shop_id')
        category_id = request.query_params.get('category_id')

        if shop_id:
            query = query & Q(shop_id=shop_id)

        if category_id:
            query = query & Q(product__category_id=category_id)

        # фильтруем и отбрасываем дуликаты
        queryset = ProductInfo.objects.filter(
            query).select_related(
            'shop', 'product__category').prefetch_related(
            'product_parameters__parameter').distinct()

        serializer = ProductInfoSerializer(queryset, many=True)

        return Response(serializer.data)
    

class BasketView(APIView):
    """
    Класс для управления корзиной 
    """

    def get(self, request: Request, *args, **kwargs):
        """
        Получить содержимое корзины
        """
        if not request.user.is_authenticated:
            return JsonResponse(
                {'Status': False, 'Error': 'Требуется авторизация'}, 
                status=403
            )

        try:
            # basket = Order.objects.filter(
            # user_id=request.user.id, state='basket').prefetch_related(
            # 'ordered_items__product_info__product__category',
            # 'ordered_items__product_info__product_parameters__parameter').annotate(
            # total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()

            basket = Order.objects.filter(
            user_id=request.user.id, state='basket').prefetch_related(
            'ordered_items__product_info__product__category',
            'ordered_items__product_info__product_parameters__parameter').annotate(
            total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).first()

            # Если корзина существует но пуста - удаляем ее
            if basket and not basket.ordered_items.exists():
                basket.delete()
                return Response({
                    'Status': True,
                    'Message': 'Корзина пуста',
                    'Data': []
                })
            
            if not basket:
                return Response({
                    'Status': True,
                    'Message': 'Корзина пуста',
                    'Data': []
                })

            # serializer = OrderSerializer(basket, many=True)
            serializer = OrderSerializer(basket)
            return Response(serializer.data)

        except Exception as e:
            return JsonResponse(
                {'Status': False, 'Error': f'Ошибка при получении корзины: {str(e)}'},
                status=500
                )
    
    def post(self, request: Request, *args, **kwargs):
        """
        Добавить товары в корзину
        """
        if not request.user.is_authenticated:
            return JsonResponse(
                {'Status': False, 'Error': 'Требуется авторизация'}, 
                status=403
            )

        item_string = request.data.get('items')
        if not item_string:
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны товары для добавления'},
                status=400
            )

        try:
            if not isinstance(item_string, list):
                return JsonResponse(
                    {'Status': False, 'Errors': 'Items должен быть списком'},
                    status=400
                )

            basket, _ = Order.objects.get_or_create(
                user_id=request.user.id, 
                state='basket'
            )

            objects_created = 0
            errors = []

            with transaction.atomic():
                for item_data in item_string:
                    # Валидация 
                    if not all(key in item_data for key in ['product_info', 'quantity']):
                        errors.append(f"Отсутствуют обязательные поля в item: {item_data}")
                        continue

                    # Проверяем наличие товара
                    try:
                        product_info = ProductInfo.objects.get(
                            id=item_data['product_info'],
                            shop__state=True,
                            quantity__gte=item_data.get('quantity', 1)
                        )
                    except ProductInfo.DoesNotExist:
                        errors.append(f"Товар с ID {item_data['product_info']} не найден или недоступен")
                        continue

                    # Проверяем количество
                    quantity = item_data['quantity']
                    if quantity <= 0:
                        errors.append(f"Некорректное количество: {quantity}")
                        continue

                    # Создаем или обновляем позицию в корзине
                    order_item, created = OrderItem.objects.get_or_create(
                        order=basket,
                        product_info=product_info,
                        defaults={'quantity': quantity}
                    )

                    if not created:
                        # Если товар уже в корзине,то увеличиваем количество
                        new_quantity = order_item.quantity + quantity
                        if new_quantity <= product_info.quantity:
                            order_item.quantity = new_quantity
                            order_item.save()
                        else:
                            errors.append(f"Недостаточно товара {product_info.product.name}. Доступно: {product_info.quantity}")
                            continue
                    
                    objects_created += 1

            response_data = {'Status': True, 'Добавлено объектов': objects_created}
            if errors:
                response_data['Errors'] = errors
                
            return JsonResponse(response_data)

        except Exception as e:
            return JsonResponse(
                {'Status': False, 'Errors': f'Ошибка при добавлении в корзину: {str(e)}'},
                status=500
            )
        

    def put(self, request: Request, *args, **kwargs):
        """
        Обновить количество товаров в корзине
        """
        if not request.user.is_authenticated:
            return JsonResponse(
                {'Status': False, 'Error': 'Требуется авторизация'}, 
                status=403
            )

        items = request.data.get('items')
        if not items or not isinstance(items, list):
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны товары для обновления'},
                status=400
            )

        try:
            basket = Order.objects.filter(
                user_id=request.user.id, 
                state='basket'
            ).first()

            if not basket:
                return JsonResponse(
                    {'Status': False, 'Errors': 'Корзина не найдена'},
                    status=404
                )

            objects_updated = 0
            errors = []

            with transaction.atomic():
                for item_data in items:
                    if not all(key in item_data for key in ['id', 'quantity']):
                        errors.append(f"Отсутствуют обязательные поля в item: {item_data}")
                        continue

                    try:
                        order_item = OrderItem.objects.get(
                            id=item_data['id'],
                            order=basket
                        )
                    except OrderItem.DoesNotExist:
                        errors.append(f"Позиция с ID {item_data['id']} не найдена в корзине")
                        continue

                    quantity = item_data['quantity']
                  
                    if quantity <= 0:
                        order_item.delete()
                        objects_updated += 1
                    elif quantity <= order_item.product_info.quantity:
                        order_item.quantity = quantity
                        order_item.save()
                        objects_updated += 1
                    else:
                        errors.append(
                            f"Недостаточно товара {order_item.product_info.product.name}. "
                            f"Доступно: {order_item.product_info.quantity}"
                        )

            response_data = {'Status': True, 'Обновлено объектов': objects_updated}
            if errors:
                response_data['Errors'] = errors
                
            return JsonResponse(response_data)

        except Exception as e:
            return JsonResponse(
                {'Status': False, 'Errors': f'Ошибка при обновлении корзины: {str(e)}'},
                status=500
            )
       
    def delete(self, request: Request, *args, **kwargs):
        """
        Удалить товары из корзины
        """
        if not request.user.is_authenticated:
            return JsonResponse(
                {'Status': False, 'Error': 'Требуется авторизация'}, 
                status=403
            )

        items = request.data.get('items')
        if not items:
            return JsonResponse(
                {'Status': False, 'Errors': 'Не указаны товары для удаления'},
                status=400
            )

        try:
            basket = Order.objects.filter(
                user_id=request.user.id, 
                state='basket'
            ).first()

            if not basket:
                return JsonResponse(
                    {'Status': False, 'Errors': 'Корзина не найдена'},
                    status=404
                )

            if isinstance(items, str):
                item_ids = [int(id.strip()) for id in items.split(',') if id.strip().isdigit()]
            elif isinstance(items, list):
                item_ids = [int(item_id) for item_id in items if str(item_id).isdigit()]
            else:
                return JsonResponse(
                    {'Status': False, 'Errors': 'Неверный формат items'},
                    status=400
                )

            if not item_ids:
                return JsonResponse(
                    {'Status': False, 'Errors': 'Не указаны ID товаров'},
                    status=400
                )

            deleted_count, _ = OrderItem.objects.filter(
                order=basket,
                id__in=item_ids
            ).delete()

            return JsonResponse({
                'Status': True, 
                'Удалено объектов': deleted_count
            })

        except Exception as e:
            return JsonResponse(
                {'Status': False, 'Errors': f'Ошибка при удалении из корзины: {str(e)}'},
                status=500
            )


class PartnerState(APIView):
    """
    Класс для управления статусом приема заказов магазином
    """

    # получить текущий статус
    def get(self, request, *args, **kwargs):
        """
        Получить текущий статус магазина
        """
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)

        shop = request.user.shop
        serializer = ShopSerializer(shop)
        return Response(serializer.data)

    # изменить текущий статус
    def post(self, request, *args, **kwargs):
        """
        Изменение статуса приема заказов
        """
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)
        state = request.data.get('state')
        if state:
            try:
                Shop.objects.filter(user_id=request.user.id).update(state=strtobool(state))
                return JsonResponse({'Status': True})
            except ValueError as error:
                return JsonResponse({'Status': False, 'Errors': str(error)}, status = 400)

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}, status = 400)
    

class PartnerOrders(APIView):
    """
        Класс для получения заказов поставщиком
    """

    def get(self, request, *args, **kwargs):
        """
        Получить заказы для магазина поставщика
        """
        
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)

        order = Order.objects.filter(
            ordered_items__product_info__shop__user_id=request.user.id).exclude(state='basket').prefetch_related(
            'ordered_items__product_info__product__category',
            'ordered_items__product_info__product_parameters__parameter').select_related('contact').annotate(
            total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()

        serializer = OrderSerializer(order, many=True)
        return Response(serializer.data)
    

class ContactView(APIView):
    """
    Класс для управления контактной информацией 
    """

  
    def get(self, request, *args, **kwargs):
        """
        Получить контакты пользователя
        """
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)
        contact = Contact.objects.filter(
            user_id=request.user.id)
        serializer = ContactSerializer(contact, many=True)
        return Response(serializer.data)

    
    def post(self, request, *args, **kwargs):
        """
        Создать новый контакт
        """
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if {'city', 'street', 'phone'}.issubset(request.data):
            # request.data._mutable = True
            # request.data.update({'user': request.user.id})
            # serializer = ContactSerializer(data=request.data)
            contact_data = request.data.copy()
            contact_data['user'] = request.user.id
            serializer = ContactSerializer(data=contact_data)

            if serializer.is_valid():
                serializer.save()
                return JsonResponse({'Status': True})
            else:
                return JsonResponse({'Status': False, 'Errors': serializer.errors})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'})

    def delete(self, request, *args, **kwargs):
        """
        Удалить контакт
        """
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        items_sting = request.data.get('items')
        if items_sting:
            items_list = items_sting.split(',')
            query = Q()
            objects_deleted = False
            for contact_id in items_list:
                if contact_id.isdigit():
                    query = query | Q(user_id=request.user.id, id=contact_id)
                    objects_deleted = True

            if objects_deleted:
                deleted_count = Contact.objects.filter(query).delete()[0]
                return JsonResponse({'Status': True, 'Удалено объектов': deleted_count})
        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'})

    def put(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            """
            Обновить контакт
            """
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if 'id' in request.data:
            if (request.data['id']).isdigit():
                contact = Contact.objects.filter(id=request.data['id'], user_id=request.user.id).first()
                print(contact)
                if contact:
                    serializer = ContactSerializer(contact, data=request.data, partial=True)
                    if serializer.is_valid():
                        serializer.save()
                        return JsonResponse({'Status': True})
                    else:
                        return JsonResponse({'Status': False, 'Errors': serializer.errors})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'})


class OrderView(APIView):
    """
    Класс для управления заказами пользователя
    """

    def get(self, request, *args, **kwargs):
        """
        Получить список заказов пользователя
        """
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)
        order = Order.objects.filter(
            user_id=request.user.id).exclude(state='basket').prefetch_related(
            'ordered_items__product_info__product__category',
            'ordered_items__product_info__product_parameters__parameter').select_related('contact').annotate(
            total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()

        serializer = OrderSerializer(order, many=True)
        return Response(serializer.data)

    # def post(self, request, *args, **kwargs):
    #     """
    #     Оформить заказ из корзины
    #     """
    #     if not request.user.is_authenticated:
    #         return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

    #     if {'id', 'contact'}.issubset(request.data):
    #         if request.data['id'].isdigit():
    #             try:
    #                 is_updated = Order.objects.filter(
    #                     user_id=request.user.id, id=request.data['id']).update(
    #                     contact_id=request.data['contact'],
    #                     state='new')
    #             except IntegrityError as error:
    #                 print(error)
    #                 return JsonResponse({'Status': False, 'Errors': 'Неправильно указаны аргументы'})
    #             else:
    #                 if is_updated:
    #                     new_order.send(sender=self.__class__, user_id=request.user.id)
    #                     return JsonResponse({'Status': True})

    #     return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}, status = 400)
    
    def post(self, request, *args, **kwargs):
        """
        Оформить заказ из корзины
        {
        "contact": 3
        }

        """
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)
        if 'contact' not in request.data:
            return JsonResponse({'Status': False, 'Errors': 'Не указан contact'}, status=400)
        
        try:
                contact_id = int(request.data['contact'])
                
                # Находим корзину пользователя. Корзина всегда 1, поэтому в запросе ее не передаем
                basket = Order.objects.filter(
                    user_id=request.user.id, 
                    state='basket'
                ).first()
                
                if not basket:
                    return JsonResponse({
                        'Status': False, 
                        'Errors': 'Корзина не найдена'
                    }, status=400)
                
                if basket.ordered_items.count() == 0:
                    return JsonResponse({
                        'Status': False, 
                        'Errors': 'Корзина пуста'
                    }, status=400)
                
                # Оформляем заказ
                basket.contact_id = contact_id
                basket.state = 'new'
                basket.save()
                
                # Отправляем сигнал о новом заказе
                new_order.send(sender=self.__class__, user_id=request.user.id, order_id=basket.id)
                
                return JsonResponse({
                    'Status': True,
                    'Message': f'Заказ #{basket.id} успешно оформлен',
                    'Order': {
                        'id': basket.id,
                        'state': 'new',
                        'contact_id': contact_id
                    }
                })
                    
        except (ValueError, TypeError):
                return JsonResponse({
                    'Status': False, 
                    'Errors': 'Некорректный формат contact ID'
                }, status=400)
        except IntegrityError as error:
                return JsonResponse({
                    'Status': False, 
                    'Errors': f'Ошибка базы данных: {str(error)}'
                })        



        # if {'id', 'contact'}.issubset(request.data):
        #     try:
        #         # Пробуем преобразовать id в число (обрабатываем и строку, и int)
        #         order_id = int(request.data['id'])
        #         contact_id = int(request.data['contact'])
                
        #         is_updated = Order.objects.filter(
        #             user_id=request.user.id, 
        #             id=order_id,
        #             state='basket'  # Добавляем фильтр по статусу 'basket'
        #         ).update(
        #             contact_id=contact_id,
        #             state='new'
        #         )
                
        #         if is_updated:
        #             # Отправляем сигнал о новом заказе
        #             new_order.send(sender=self.__class__, user_id=request.user.id, order_id=request.order.id)
        #             return JsonResponse({'Status': True})
        #         else:
        #             return JsonResponse({
        #                 'Status': False, 
        #                 'Errors': 'Корзина не найдена или уже оформлена'
        #             }, status=400)
                    
        #     except (ValueError, TypeError):
        #         return JsonResponse({
        #             'Status': False, 
        #             'Errors': 'Некорректный формат ID'
        #         }, status=400)
        #     except IntegrityError as error:
        #         return JsonResponse({
        #             'Status': False, 
        #             'Errors': f'Ошибка базы данных: {str(error)}'
        #         })

        # return JsonResponse({
        #     'Status': False, 
        #     'Errors': 'Не указаны все необходимые аргументы'
        # }, status=400)
    

class PartnerOrderItemQuantity(APIView):
    """Изменение количества товаров в заказе"""

    def patch(self, request):
        """
        Обновление количества товаров в заказе
        
        {
            "order_id": 123,
            "updates": [
                {"item_id": 456, "quantity": 3}
            ]
        }
        """
        serializer = PartnerOrderItemUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return JsonResponse({
                'Status': False,
                'Errors': serializer.errors
            }, status=400)
        
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)   
           
        order_id = serializer.validated_data['order_id']
        updates = serializer.validated_data['updates']
        order = get_object_or_404(Order,
            id=order_id,
            ordered_items__product_info__shop__user_id=request.user.id
        )
        
        changes = []  # Список для всех изменений
        
        for update in updates:
            item_id = update['item_id']
            new_quantity = update['quantity']
            
            # Поиск товара
            order_item = get_object_or_404(
                OrderItem,
                id=item_id,
                order=order,
                product_info__shop__user_id=request.user.id
)
             
            
            # Проверка изменения
            old_quantity = order_item.quantity
            if new_quantity == old_quantity:
                continue
            
            # Создание записи об изменении
            change_record = {
                'item_id': order_item.id,
                'product_name': order_item.product_info.product.name,
                'old_quantity': old_quantity,
                'new_quantity': new_quantity,
                'price': order_item.product_info.price,
                'action': 'updated' if new_quantity > 0 else 'removed'
            }
            
            # Добавление в список изменений
            changes.append(change_record)
            
            # Применение изменения
            if new_quantity == 0:
                order_item.delete()
            else:
                order_item.quantity = new_quantity
                order_item.save()
        
        # Отправка сигнала
        if changes:
            order_item_quantity_changed.send(
                sender=self.__class__,
                order_id=order.id,
                user_id=order.user.id,
                changes=changes,
                changed_by=request.user.id
            )
        
        return JsonResponse({
            'Status': True,
            'Message': f'Обновлено {len(changes)} товар(ов)',
            'Changes': changes
        })
    

class PartnerOrderStatus(APIView):
    """ Изменение статуса заказа магазином """

    def patch(self, request):
        """
        Изменить статус заказа 
        {
            "order_id": 1,
            "status": "confirmed"
        }
        """
        
        #  Валидация 
        serializer = PartnerOrderStatusSerializer(data=request.data)
        if not serializer.is_valid():
            return JsonResponse({
                'Status': False,
                'Errors': serializer.errors
            }, status=400)
       
        order_id = serializer.validated_data['order_id']
        new_status = serializer.validated_data['status']
        

        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)

        # Ищем заказы, статус которых можно менять
        order = get_object_or_404(
            Order,
            id=order_id,
            ordered_items__product_info__shop__user_id=request.user.id,
            state__in=['new', 'confirmed', 'assembled', 'sent']  
        )

        #  Проверяем, что статус  изменился
        old_status = order.state
        if old_status == new_status:
            return JsonResponse({'Status': True, 'Message': 'Статус не изменился'})

       
        # if old_status == 'canceled':
        #     return JsonResponse({
        #         'Status': False,
        #         'Error': 'Нельзя изменить статус отмененного заказа'
        #     }, status=400)

        # if old_status == 'delivered':
        #     return JsonResponse({
        #         'Status': False,
        #         'Error': 'Нельзя изменить статус доставленного заказа'
        #     }, status=400)

        
        # Двигать статус можно только "вперед"
        status_flow = ['new', 'confirmed', 'assembled', 'sent', 'delivered']
        if old_status in status_flow and new_status in status_flow:
            old_index = status_flow.index(old_status)
            new_index = status_flow.index(new_status)
            if new_index < old_index:  
                return JsonResponse({
                    'Status': False,
                    'Error': f'Нельзя изменить статус с "{old_status}" на "{new_status}"'
                }, status=400)

        
        order.state = new_status
        order.save()

        # Отправляем сигнал 
      
        order_status_changed.send(
            sender=self.__class__,
            order_id=order.id,
            user_id=order.user.id,
            old_status=old_status,
            new_status=new_status,
            updated_by=request.user.id
        )
        
        return JsonResponse({
            'Status': True,
            'Message': f'Статус заказа #{order_id} изменен на "{order.get_state_display()}"',
            'Order': {
                'id': order.id,
                'old_status': old_status,
                'new_status': new_status,
                'new_status_display': order.get_state_display()
            }
        })
    
