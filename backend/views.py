from django.shortcuts import render
from django.db import transaction
# from distutils.util import strtobool

from setuptools._distutils.util import strtobool
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
from rest_framework.permissions import IsAuthenticated
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from ujson import loads as load_json
from yaml import load as load_yaml, Loader
from django.utils import timezone
from datetime import timedelta
from rest_framework.pagination import PageNumberPagination
from .models import User, USER_TYPE_CHOICES


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
    

class RegisterAccount(APIView):
    """
    Класс для регистрации пользователей
    """

    def post(self, request, *args, **kwargs):
        """
        Process a POST request and create a new user.
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
                    token = ConfirmEmailToken.objects.create(user=user)
                    # #  Создаем авторизационный токен
                    # from rest_framework.authtoken.models import Token
                    # api_token, created = Token.objects.get_or_create(user=user)                  
                    # Отправляем email 
                    self._send_confirmation_email(user.email, token.key)
                    
                    return JsonResponse({'Status': True})
                else:
                    return JsonResponse({'Status': False, 'Errors': user_serializer.errors})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'}, status = 400)

    def _send_confirmation_email(self, email, token):
        """
        Заглушка для отправки email 
        """
        print(f"Confirmation email to: {email}")
        # print(f"Token: {token}")
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

                 # СОЗДАЕМ АВТОРИЗАЦИОННЫЙ ТОКЕН API
                from rest_framework.authtoken.models import Token
                api_token, created = Token.objects.get_or_create(user=token.user)

                token.delete()
                return JsonResponse({'Status': True})
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
        Поиск товаров с фильтрацией по магазину, категории и другим параметрам
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
            basket = Order.objects.filter(
            user_id=request.user.id, state='basket').prefetch_related(
            'ordered_items__product_info__product__category',
            'ordered_items__product_info__product_parameters__parameter').annotate(
            total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()

            if not basket:
                return Response({
                    'Status': True,
                    'Message': 'Корзина пуста',
                    'Data': []
                })

            serializer = OrderSerializer(basket, many=True)
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


class PartnerUpdate(APIView):
    """
    Класс для обновления информации о поставщике
    """

    def post(self, request, *args, **kwargs):
        """
        Импорт прайс-листа поставщика из YAML файла по URL
        """
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)

        url = request.data.get('url')
        if url:
            validate_url = URLValidator()
            try:
                validate_url(url)
            except ValidationError as e:
                return JsonResponse({'Status': False, 'Error': str(e)})
            else:
                stream = get(url).content

                data = load_yaml(stream, Loader=Loader)

                shop, _ = Shop.objects.get_or_create(name=data['shop'], user_id=request.user.id)
                for category in data['categories']:
                    category_object, _ = Category.objects.get_or_create(id=category['id'], name=category['name'])
                    category_object.shops.add(shop.id)
                    category_object.save()
                ProductInfo.objects.filter(shop_id=shop.id).delete()
                for item in data['goods']:
                    product, _ = Product.objects.get_or_create(name=item['name'], category_id=item['category'])

                    product_info = ProductInfo.objects.create(product_id=product.id,
                                                              external_id=item['id'],
                                                              model=item['model'],
                                                              price=item['price'],
                                                              price_rrc=item['price_rrc'],
                                                              quantity=item['quantity'],
                                                              shop_id=shop.id)
                    for name, value in item['parameters'].items():
                        parameter_object, _ = Parameter.objects.get_or_create(name=name)
                        ProductParameter.objects.create(product_info_id=product_info.id,
                                                        parameter_id=parameter_object.id,
                                                        value=value)

                return JsonResponse({'Status': True})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'})
    

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
                return JsonResponse({'Status': False, 'Errors': str(error)})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'})
    

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
            if str(request.data['id']).isdigit():
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

    def post(self, request, *args, **kwargs):
        """
        Оформить заказ из корзины
        """
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Log in required'}, status=403)

        if {'id', 'contact'}.issubset(request.data):
            if request.data['id'].isdigit():
                try:
                    is_updated = Order.objects.filter(
                        user_id=request.user.id, id=request.data['id']).update(
                        contact_id=request.data['contact'],
                        state='new')
                except IntegrityError as error:
                    print(error)
                    return JsonResponse({'Status': False, 'Errors': 'Неправильно указаны аргументы'})
                else:
                    if is_updated:
                        new_order.send(sender=self.__class__, user_id=request.user.id)
                        return JsonResponse({'Status': True})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'})