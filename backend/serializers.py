from rest_framework import serializers
from backend.models import User, Category, Shop, ProductInfo, Product, ProductParameter, OrderItem, Order, Contact, USER_TYPE_CHOICES
from backend.models import STATE_CHOICES

class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ('id', 'city', 'street', 'house', 'structure', 'building', 'apartment', 'user', 'phone')
        read_only_fields = ('id',)
        extra_kwargs = {
            'user': {'write_only': True}
        }

class UserSerializer(serializers.ModelSerializer):
    contacts = ContactSerializer(read_only=True, many=True)
    type = serializers.ChoiceField(
        choices=USER_TYPE_CHOICES,
        default='buyer',  
        required=False    
    )

    class Meta:
        model = User
        fields = ('id', 'first_name', 'last_name', 'email', 'company', 'position', 'contacts', 'type')
        read_only_fields = ('id', 'contacts', 'is_active')
    
    def validate_email(self, value):
        """
        Проверка уникальности email в сериализаторе
        """
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Пользователь с таким email уже существует")
        return value

    def validate_type(self, value):
        """Проверка типа"""
        valid_types = dict(USER_TYPE_CHOICES).keys()
        if value not in valid_types:
            raise serializers.ValidationError(
                f"Тип пользователя должен быть: {', '.join(valid_types)}"
            )
        return value

# class UserSerializer(serializers.ModelSerializer):
#     class Meta:
#         model = User
#         fields = ['first_name', 'last_name', 'email', 'company', 'position']
    
#     def validate_email(self, value):
#         """
#         Проверка уникальности email в сериализаторе
#         """
#         if User.objects.filter(email=value).exists():
#             raise serializers.ValidationError("Пользователь с таким email уже существует")
#         return value
    
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('id', 'name',)
        read_only_fields = ('id',)


class ShopSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shop
        fields = ('id', 'name', 'state',)
        read_only_fields = ('id',)


class ProductSerializer(serializers.ModelSerializer):
    category = serializers.StringRelatedField()

    class Meta:
        model = Product
        fields = ('name', 'category',)


class ProductParameterSerializer(serializers.ModelSerializer):
    parameter = serializers.StringRelatedField()

    class Meta:
        model = ProductParameter
        fields = ('parameter', 'value',)


class ProductInfoSerializer(serializers.ModelSerializer):
    product = ProductSerializer(read_only=True)
    product_parameters = ProductParameterSerializer(read_only=True, many=True)

    class Meta:
        model = ProductInfo
        fields = ('id', 'model', 'product', 'shop', 'quantity', 'price', 'price_rrc', 'product_parameters',)
        read_only_fields = ('id',)


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ('id', 'product_info', 'quantity', 'order',)
        read_only_fields = ('id',)
        extra_kwargs = {
            'order': {'write_only': True}
        }


class OrderItemCreateSerializer(OrderItemSerializer):
    product_info = ProductInfoSerializer(read_only=True)


class OrderSerializer(serializers.ModelSerializer):
    ordered_items = OrderItemCreateSerializer(read_only=True, many=True)

    total_sum = serializers.IntegerField()
    contact = ContactSerializer(read_only=True)

    class Meta:
        model = Order
        fields = ('id', 'ordered_items', 'state', 'dt', 'total_sum', 'contact',)
        read_only_fields = ('id',)


class PartnerOrderItemUpdateSerializer(serializers.Serializer):

    order_id = serializers.IntegerField(min_value=1)
    updates = serializers.ListField(
        child=serializers.DictField(),
        min_length=1  
    )
    
    def validate_updates(self, value):
        """Дополнительная валидация списка updates"""
        for i, update in enumerate(value):
            # Проверяем обязательные поля
            if 'id' not in update or 'quantity' not in update:
                raise serializers.ValidationError(
                    f"Элемент #{i}: отсутствуют id или quantity"
                )
            
            # Проверяем типы
            try:
                id = int(update['id'])
                if id <= 0:
                    raise serializers.ValidationError(
                        f"Элемент #{i}: item_id должен быть положительным числом"
                    )
            except (ValueError, TypeError):
                raise serializers.ValidationError(
                    f"Элемент #{i}: некорректный item_id"
                )
            
            try:
                quantity = int(update['quantity'])
                if quantity < 0:
                    raise serializers.ValidationError(
                        f"Элемент #{i}: количество не может быть отрицательным"
                    )
            except (ValueError, TypeError):
                raise serializers.ValidationError(
                    f"Элемент #{i}: некорректное количество"
                )
        
        return value
    
class PartnerOrderStatusSerializer(serializers.Serializer):
    """Валидация запроса на изменение статуса заказа"""
    
    order_id = serializers.IntegerField(min_value=1)
    status = serializers.CharField(max_length=20)
    
    def validate_status(self, value):
        """Проверка допустимости статуса"""
        valid_statuses = [code for code, _ in STATE_CHOICES if code != 'basket']
        
        if value not in valid_statuses:
            status_list = ", ".join([f"'{s}'" for s in valid_statuses])
            raise serializers.ValidationError(
                f'Недопустимый статус. Допустимо: {status_list}'
            )
        
        return value