from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.urls import reverse
from django.contrib.admin import SimpleListFilter
from django.db.models import Count, Q
from django.utils.translation import gettext_lazy as _
from django.contrib.admin import AdminSite
from backend.models import User, Shop, Category, Product, ProductInfo, Parameter, ProductParameter, Order, OrderItem, \
    Contact, ConfirmEmailToken


def is_shop_user(request):
    """Является ли пользователь магазином"""
    user = request.user

    if not user or user.is_anonymous:
        return False
    return user.type == 'shop'

def is_buyer_user(request):
    """Является ли пользователь покупателем"""
    user = request.user
    if not user or user.is_anonymous:
        return False
    return user.type == 'buyer'

def is_superuser(request):
    """Является ли пользователь суперадмином"""
    user = request.user
  
    if not user or user.is_anonymous:
        return False
    return user.is_superuser


class BaseOrderItemAdmin:
    """Базовый класс с общей логикой для OrderItem"""
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return self._filter_orderitem_queryset(request, qs)
    
    def _filter_orderitem_queryset(self, request, queryset):
        """Метод фильтрации"""
        if not request.user.is_authenticated:
            return queryset.none()
        
        if is_superuser(request):
            return queryset
        
        if is_shop_user(request):
            shop = Shop.objects.filter(user=request.user).first()
            if shop:
                return queryset.filter(product_info__shop=shop)
        
        elif is_buyer_user(request):
            return queryset.filter(order__user=request.user)
        
        return queryset.none()


class ReadOnlyAdmin(admin.ModelAdmin):
    """Админка только для чтения (для покупателей и магазинов), но суперадмины имеют полный доступ"""
    
    def has_module_permission(self, request):
        """Показывать модель в меню всем пользователям"""
        try:
            return request.user and not request.user.is_anonymous and request.user.is_staff
        except:
            return False
    
    def has_view_permission(self, request, obj=None):
        try:
            return request.user and not request.user.is_anonymous and request.user.is_staff
        except:
            return False


    
    def has_change_permission(self, request, obj=None):
        # Суперадмины могут менять
        return is_superuser(request)
    
    def has_add_permission(self, request):
        # Суперадмины могут добавлять
        return is_superuser(request)
    
    def has_delete_permission(self, request, obj=None):
        # Суперадмины могут удалять
        return is_superuser(request)

    def get_readonly_fields(self, request, obj=None):
        """Для суперадминов - нет readonly, для остальных - все поля"""
        if is_superuser(request):
            return []
        
        try:
            if hasattr(self, 'model') and self.model:
                return [field.name for field in self.model._meta.fields]
        except:
            pass
        
        return []


class ShopFilter(SimpleListFilter):
    """Фильтр по магазину"""
    title = 'Магазин'
    parameter_name = 'shop'

    def lookups(self, request, model_admin):
        shops = Shop.objects.all()
        return [(shop.id, shop.name) for shop in shops]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(shop__id=self.value())
        return queryset


class OrderItemInline(BaseOrderItemAdmin, admin.TabularInline):
    """Товары в заказе - магазины могут менять количество и удалять свои товары"""
    model = OrderItem
    extra = 0
    fields = ['product_info', 'quantity', 'get_price', 'get_total']
    readonly_fields = ['get_price', 'get_total', 'get_product_name']
    can_delete = True  
    
    def get_product_name(self, obj):
        if obj and obj.product_info and obj.product_info.product:
            return obj.product_info.product.name
        return '-'
    get_product_name.short_description = 'Товар'
    
    def get_price(self, obj):
        if obj and obj.product_info:
            return f"{obj.product_info.price} руб."
        return '-'
    get_price.short_description = 'Цена за шт.'
    
    def get_total(self, obj):
        if obj and obj.product_info:
            total = obj.quantity * obj.product_info.price
            return f"{total} руб."
        return '-'
    get_total.short_description = 'Сумма'
    
    def has_add_permission(self, request, obj):
        return is_superuser(request)
    
    def has_delete_permission(self, request, obj=None):
        """Магазины могут удалять только свои позиции"""
        if not request.user.is_authenticated:
            return False
        
        if is_superuser(request):
            return True
        
        # Если obj передан (это OrderItem) и это магазин
        if is_shop_user(request) and obj:
            if hasattr(obj, 'product_info'):
                shop = Shop.objects.filter(user=request.user).first()
                if shop and obj.product_info:
                    return obj.product_info.shop == shop    
        return True
    
    def has_change_permission(self, request, obj=None):
        """Магазины могут менять только свои позиции"""
        if not request.user.is_authenticated:
            return False
        
        if is_superuser(request):
            return True
        
        # Если obj передан (это OrderItem) и это магазин
        if is_shop_user(request) and obj:
            if hasattr(obj, 'product_info'):
                shop = Shop.objects.filter(user=request.user).first()
                if shop and obj.product_info:
                    return obj.product_info.shop == shop
        return True
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Ограничиваем выбор товара для магазинов"""
        if db_field.name == "product_info" and is_shop_user(request):
            # Магазины могут выбрать только свои товары
            shop = Shop.objects.filter(user=request.user).first()
            if shop:
                kwargs["queryset"] = ProductInfo.objects.filter(shop=shop)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def get_readonly_fields(self, request, obj=None):
        """Настраиваем readonly поля"""
        readonly_fields = ['get_price', 'get_total', 'get_product_name']
        
        if not request.user.is_authenticated:
            return readonly_fields + ['product_info', 'quantity']
        
        # Суперадмины могут менять всё
        if is_superuser(request):
            return readonly_fields
        
        # Магазины могут менять только количество
        if is_shop_user(request):
            return readonly_fields + ['product_info']  
        
        # Покупатели не могут ничего менять
        return readonly_fields + ['product_info', 'quantity']
    
    def get_formset(self, request, obj=None, **kwargs):
        """Переопределяем formset для проверки прав"""
        formset = super().get_formset(request, obj, **kwargs)

        if obj and hasattr(obj, 'ordered_items'):
            # Проверяем права магазина на этот заказ
            if is_shop_user(request):
                shop = Shop.objects.filter(user=request.user).first()
                if shop:
                    # Проверяем есть ли у магазина товары в этом заказе
                    if not obj.ordered_items.filter(product_info__shop=shop).exists():
                        formset.form.base_fields = {}
        
        return formset


class ProductParameterInline(admin.TabularInline):
    """Параметры товара (inline)"""
    model = ProductParameter
    extra = 1
    fields = ['parameter', 'value']


class CustomUserAdmin(UserAdmin):
    """
    Панель управления пользователями
    """
    model = User
    list_display = ('email', 'first_name', 'last_name', 'type', 'is_active', 'is_staff', 'is_superuser')
    list_filter = ( 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('email', 'first_name', 'last_name', 'company')
    ordering = ('last_name',)
    
    fieldsets = (
        (None, {'fields': ('email', 'password', 'type')}),
        ('Персональная информация', {'fields': ('first_name', 'last_name', 'company', 'position')}),
        ('Права доступа', {
            'fields': ('is_active', 'is_staff', 'is_superuser'),
        }),
        ('Активность', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'type', 'password1', 'password2', 'is_staff', 'is_superuser'),
        }),
    )
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Суперадмины видят всё
        if is_superuser(request):
            return qs
        # Покупатели и магазины видят только магазины
        elif is_shop_user(request) or is_buyer_user(request):
            return qs.filter(type='shop')
        return qs
    
    def has_module_permission(self, request):
        """Все пользователи видят раздел"""
        return request.user.is_authenticated and request.user.is_staff
    
    def has_view_permission(self, request, obj=None):
        """Кто может открывать список пользователей"""
        return request.user.is_authenticated and request.user.is_staff
    
    def save_model(self, request, obj, form, change):
        """Автоматически устанавливаем is_staff=True для магазинов и покупателей (при создании в админке)"""
        if obj.type in ['shop', 'buyer']:
            obj.is_staff = True
        super().save_model(request, obj, form, change)


class ShopAdmin(ReadOnlyAdmin):
    list_display = ('name', 'user_email', 'url', 'state')
    list_filter = ('state',)
    search_fields = ('name', 'user__email', 'url')
    
    
    def user_email(self, obj):
        return obj.user.email if obj.user else '-'
    user_email.short_description = 'Пользователь'


class CategoryAdmin(ReadOnlyAdmin):
    list_display = ('name', 'get_shops_count', 'get_products_count')
    search_fields = ('name',)
    ordering = ('name',)
    # УБИРАЕМ readonly_fields здесь!
    
    def get_shops_count(self, obj):
        return obj.shops.count()
    get_shops_count.short_description = 'Количество магазинов'
    
    def get_products_count(self, obj):
        return obj.products.count()
    get_products_count.short_description = 'Количество товаров'


class ProductAdmin(ReadOnlyAdmin):
    list_display = ('name', 'category', 'display_parameters')
    list_filter = ('category',)
    search_fields = ('name',)
    
    def display_parameters(self, obj):
        params = ProductParameter.objects.filter(product_info__product=obj)[:4]
        return ", ".join([f"{p.parameter.name}: {p.value}" for p in params])[:100]
    display_parameters.short_description = 'Параметры (первые 4)'


class ProductInfoAdmin(ReadOnlyAdmin):
    list_display = ('get_product_name', 'shop', 'model', 'price', 'price_rrc', 'quantity', 'category_display')
    list_filter = (ShopFilter, 'product__category')
    search_fields = ('product__name', 'model')

    inlines = [ProductParameterInline]  
    def get_product_name(self, obj):
        return obj.product.name
    get_product_name.short_description = 'Товар'
    
    def category_display(self, obj):
        return obj.product.category.name
    category_display.short_description = 'Категория'


class ParameterAdmin(ReadOnlyAdmin):
    list_display = ('name', 'get_products_count')
    search_fields = ('name',)
    
    def get_products_count(self, obj):
        return obj.product_parameters.count()
    get_products_count.short_description = 'Используется в товарах'


class ProductParameterAdmin(ReadOnlyAdmin):
    list_display = ('get_product_name', 'parameter', 'value', 'get_shop')
    list_filter = ('parameter',)
    search_fields = ('product_info__product__name', 'parameter__name')
    
    def get_product_name(self, obj):
        return obj.product_info.product.name
    get_product_name.short_description = 'Товар'
    
    def get_shop(self, obj):
        return obj.product_info.shop.name
    get_shop.short_description = 'Магазин'


class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'dt', 'state', 'user_email', 'contact_info', 'display_total_sum', 'items_count')
    list_filter = ('state', 'dt')
    search_fields = ('id', 'user__email', 'contact__phone')
    readonly_fields = ('dt', 'user', 'contact', 'updated_at', 'display_total_calculated')
    inlines = [OrderItemInline]
    actions = ['mark_as_confirmed', 'mark_as_assembled', 'mark_as_sent', 'mark_as_delivered', 'mark_as_canceled']
    
    # fieldsets = (
    #     (None, {
    #         'fields': ('user', 'state', 'contact')
    #     }),
    #     ('Информация о заказе', {
    #         'fields': ('dt', 'updated_at', 'display_total_calculated'),
    #         'classes': ('collapse',)
    #     }),
    # )
    def get_fieldsets(self, request, obj=None):
        """Динамическое определение fieldsets"""
        if is_superuser(request) and not obj:
            # Суперадмин создает новый заказ 
            return (
                (None, {
                    'fields': ('user', 'state', 'contact')
                }),
            )
        elif is_superuser(request) and obj:
            # Суперадмин редактирует существующий заказ
            return (
                (None, {
                    'fields': ('user', 'state', 'contact')
                }),
                ('Информация о заказе', {
                    'fields': ('dt', 'updated_at'),
                    'classes': ('collapse',)
                }),
            )

        # покупатели и магазины
        return (
            (None, {'fields': ('user', 'state', 'contact')}),
            ('Информация о заказе', {
                'fields': ('dt', 'updated_at', 'display_total_calculated'),
                'classes': ('collapse',)
            }),
        )


    def user_email(self, obj):
        return obj.user.email if obj.user else '-'
    user_email.short_description = 'Пользователь'
    
    def contact_info(self, obj):
        if obj.contact:
            return f"{obj.contact.city}, {obj.contact.phone}"
        return '-'
    contact_info.short_description = 'Контакт'
    
    def display_total_sum(self, obj):
        total = 0
        for item in obj.ordered_items.all():
            if hasattr(item, 'product_info') and item.product_info:
                total += item.quantity * item.product_info.price
        return f"{total} ₽"
    display_total_sum.short_description = 'Сумма'
    
    def display_total_calculated(self, obj):
        total = 0
        for item in obj.ordered_items.all():
            if hasattr(item, 'product_info') and item.product_info:
                total += item.quantity * item.product_info.price
        return f"{total} ₽"
    display_total_calculated.short_description = 'Общая сумма'
    
    def items_count(self, obj):
        return obj.ordered_items.count()
    items_count.short_description = 'Товаров'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        
        if not request.user.is_authenticated:
            return qs.none()
        
        # Суперадмины видят ВСЁ
        if is_superuser(request):
            return qs
        
        # Для магазинов показываем только заказы с их товарами
        if is_shop_user(request):
            shop = Shop.objects.filter(user=request.user).first()
            if shop:
                return qs.filter(
                    ordered_items__product_info__shop=shop
                ).annotate(
                    shop_items_count=Count('ordered_items', filter=Q(ordered_items__product_info__shop=shop))
                ).filter(shop_items_count__gt=0).distinct()
            return qs.none() # если нет заказов
        
        # Для покупателей показываем только их заказы
        elif is_buyer_user(request):
            return qs.filter(user=request.user)        
        return qs
    
    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        # Для магазинов скрываем поле пользователя
        if request.user.is_authenticated and request.user.type == 'shop':
            fieldsets = (
                (None, {
                    'fields': ('state', 'contact')
                }),
                ('Информация о заказе', {
                    'fields': ('dt', 'updated_at', 'display_total_calculated'),
                    'classes': ('collapse',)
                }),
            )
        return fieldsets
    
    def get_list_display(self, request):
        base_list = super().get_list_display(request)
        # Для магазинов скрываем email пользователя
        if request.user.is_authenticated and request.user.type == 'shop':
            return [field for field in base_list if field != 'user_email']
        return base_list

    def get_readonly_fields(self, request, obj=None):
        """Для суперадминов - нет readonly, для остальных - все поля"""
        if is_superuser(request):
            if obj:  
                return ['dt', 'updated_at']
            else:  
                return []  
    def has_module_permission(self, request):
        """Все staff пользователи видят заказы в меню"""
        return request.user.is_authenticated and request.user.is_staff
    
    def has_view_permission(self, request, obj=None):
        """Все staff пользователи могут смотреть"""
        return request.user.is_authenticated and request.user.is_staff
    
    def has_change_permission(self, request, obj=None):
        """Кто может изменять заказы"""
        if not request.user.is_authenticated:
            return False
        
        # Суперадмины могут вс
        if request.user.is_superuser:
            return True
        
        # Покупатели могут менять только свои заказы
        if is_buyer_user(request) and obj:
            return obj.user == request.user
        
        # Магазины могут менять заказы со своими товарами
        if is_shop_user(request):
            if obj:  
                shop = Shop.objects.filter(user=request.user).first()
                if shop:
                    return obj.ordered_items.filter(product_info__shop=shop).exists()
            return True  
        
        return False
    
    def has_add_permission(self, request):
        return is_superuser(request)
    
    def has_delete_permission(self, request, obj=None):
        return is_superuser(request)
    
    #  Действия со статусом
    def mark_as_confirmed(self, request, queryset):
        "Установить статус confirmed"
        count = 0
        for order in queryset:
            if self.has_change_permission(request, order):
                order.state = 'confirmed'
                order.save()
                count += 1
        self.message_user(request, f"{count} заказов подтверждено")
    mark_as_confirmed.short_description = "Подтвердить выбранные заказы"
    
    def mark_as_assembled(self, request, queryset):
        "Установить статус assembled"
        count = 0
        for order in queryset:
            if self.has_change_permission(request, order):
                order.state = 'assembled'
                order.save()
                count += 1
        self.message_user(request, f"{count} заказов собрано")
    mark_as_assembled.short_description = "Отметить как собранные"
    
    def mark_as_sent(self, request, queryset):
        "Установить статус assembled"
        count = 0
        for order in queryset:
            if self.has_change_permission(request, order):
                order.state = 'sent'
                order.save()
                count += 1
        self.message_user(request, f"{count} заказов отправлено")
    mark_as_sent.short_description = "Отметить как отправленные"
    
    def mark_as_delivered(self, request, queryset):
        "Установить статус delivered"
        count = 0
        for order in queryset:
            if self.has_change_permission(request, order):
                order.state = 'delivered'
                order.save()
                count += 1
        self.message_user(request, f"{count} заказов доставлено")
    mark_as_delivered.short_description = "Отметить как доставленные"
    
    def mark_as_canceled(self, request, queryset):
        "Установить статус canceled"
        count = 0
        for order in queryset:
            if self.has_change_permission(request, order):
                order.state = 'canceled'
                order.save()
                count += 1
        self.message_user(request, f"{count} заказов отменено")
    mark_as_canceled.short_description = "Отменить выбранные заказы"


class OrderItemAdmin(BaseOrderItemAdmin, admin.ModelAdmin):  
    list_display = ('id', 'order_link', 'product_name', 'shop_name', 'quantity', 'price_per_item', 'total_price')
    list_filter = ('product_info__shop',)
    search_fields = ('order__id', 'product_info__product__name')
    actions = ['delete_selected_items']
    
    def order_link(self, obj):
        if obj.order:
            url = reverse('admin:backend_order_change', args=[obj.order.id])
            return format_html('<a href="{}">Заказ #{}</a>', url, obj.order.id)
        return 'Нет заказа'
    order_link.short_description = 'Заказ'
    
    def product_name(self, obj):
        if obj.product_info and obj.product_info.product:
            return obj.product_info.product.name
        return '-'
    product_name.short_description = 'Товар'
    
    def shop_name(self, obj):
        if obj.product_info and obj.product_info.shop:
            return obj.product_info.shop.name
        return '-'
    shop_name.short_description = 'Магазин'
    
    def price_per_item(self, obj):
        if obj.product_info:
            return f"{obj.product_info.price} ₽"
        return '-'
    price_per_item.short_description = 'Цена за шт.'
    
    def total_price(self, obj):
        if obj.product_info:
            total = obj.quantity * obj.product_info.price
            return f"{total} ₽"
        return '-'
    total_price.short_description = 'Сумма'
      
    def has_module_permission(self, request):
        """Показывать в меню всем пользователям"""
        return request.user.is_authenticated and request.user.is_staff
    
    def has_view_permission(self, request, obj=None):
        """Кто может просматривать позиции заказа"""
        if not request.user.is_authenticated:
            return False
        
        if is_superuser(request):
            return True
        
        if is_shop_user(request):
            if obj:
                # Безопасная проверка с hasattr
                if hasattr(obj, 'product_info') and obj.product_info:
                    shop = Shop.objects.filter(user=request.user).first()
                    if shop:
                        return obj.product_info.shop == shop
                return False
            return True  # Разрешаем доступ к списку
        
        if is_buyer_user(request):
            if obj:
                return obj.order.user == request.user
            return True  # Разрешаем доступ к списку
        
        return False
    
    def has_change_permission(self, request, obj=None):
        """Магазины могут менять количество в своих позициях"""
        if not request.user.is_authenticated:
            return False
        
        if is_superuser(request):
            return True
        
        if is_shop_user(request) and obj:
            # Безопасная проверка с hasattr
            if hasattr(obj, 'product_info') and obj.product_info:
                shop = Shop.objects.filter(user=request.user).first()
                if shop:
                    return obj.product_info.shop == shop
        
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Магазины могут удалять свои позиции"""
        if not request.user.is_authenticated:
            return False
        
        if is_superuser(request):
            return True
        
        if is_shop_user(request) and obj:
            # Безопасная проверка с hasattr
            if hasattr(obj, 'product_info') and obj.product_info:
                shop = Shop.objects.filter(user=request.user).first()
                if shop:
                    return obj.product_info.shop == shop
        
        return False
    
    def has_add_permission(self, request):
        return is_superuser(request)
    
    def get_readonly_fields(self, request, obj=None):
        """Настраиваем readonly поля в зависимости от пользователя"""
        if not request.user.is_authenticated:
            return ['order', 'product_info', 'quantity']
        
        if is_superuser(request):
            # Суперадмины могут менять всё
            return []
        
        if is_shop_user(request) and obj:
            # Магазины могут менять только количество
            return ['order', 'product_info']
        
        # Для всех остальных все поля readonly
        return ['order', 'product_info', 'quantity']
    
    def get_fields(self, request, obj=None):
        """Определяем какие поля показывать в форме"""
        if is_superuser(request):
            return ['order', 'product_info', 'quantity']
        
        if request.user.type == 'shop':
            # Магазины видят только количество
            return ['quantity']
        
        return ['order', 'product_info', 'quantity']
    
    def delete_selected_items(self, request, queryset):
        """Массовое удаление выбранных позиций"""
        deleted_count = 0
        for item in queryset:
            if self.has_delete_permission(request, item):
                item.delete()
                deleted_count += 1
        
        if deleted_count:
            self.message_user(request, f"Удалено {deleted_count} позиций заказа")
        else:
            self.message_user(request, "Нет прав для удаления выбранных позиций", level='warning')
    
    delete_selected_items.short_description = "Удалить выбранные позиции"
    
    def save_model(self, request, obj, form, change):
        """Удаляем если количество = 0"""
        if obj.quantity == 0:
            if obj.pk:
                obj.delete()
                return
            return
        
        # Для магазинов проверяем права на изменение
        if is_shop_user(request) and change:
            if not self.has_change_permission(request, obj):
                from django.contrib import messages
                messages.error(request, "Нет прав для изменения этой позиции заказа")
                return
        
        super().save_model(request, obj, form, change)
    
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Ограничиваем выбор для магазинов"""
        if db_field.name == "product_info" and is_shop_user(request):
            # Магазины могут выбрать только свои товары
            shop = Shop.objects.filter(user=request.user).first()
            if shop:
                kwargs["queryset"] = ProductInfo.objects.filter(shop=shop)
        
        if db_field.name == "order" and is_shop_user(request):
            # Магазины могут выбрать только заказы со своими товарами
            shop = Shop.objects.filter(user=request.user).first()
            if shop:
                kwargs["queryset"] = Order.objects.filter(
                    ordered_items__product_info__shop=shop
                ).distinct()
        
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


class ContactAdmin(admin.ModelAdmin):
    list_display = ('user_email', 'city', 'street', 'house', 'phone')
    search_fields = ('user__email', 'city', 'phone')
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'Пользователь'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not request.user.is_authenticated:
            return qs.none()
        
        if is_superuser(request):
            return qs
        if is_buyer_user(request):
            return qs.filter(user=request.user)
        elif is_shop_user(request):
            return qs.none()
        return qs
    
    def has_module_permission(self, request):
        return is_buyer_user(request) or is_superuser(request)
    
    def has_view_permission(self, request, obj=None):
        if not request.user.is_authenticated:
            return False
        
        if is_superuser(request):
            return True
        if is_buyer_user(request):
            if obj:
                return obj.user == request.user
            return True
        return False
    
    def has_change_permission(self, request, obj=None):
        if not request.user.is_authenticated:
            return False        
        if is_superuser(request):
            return True
       
        if is_buyer_user(request) and obj:
            return obj.user == request.user       
        return False
    
    def has_add_permission(self, request):
        return is_buyer_user(request) or is_superuser(request)
    
    def has_delete_permission(self, request, obj=None):
        if not request.user.is_authenticated:
            return False
        
        if is_superuser(request):
            return True
        if is_buyer_user(request) and obj:
            return obj.user == request.user
        return False

    def save_model(self, request, obj, form, change):
        """При создании контакта автоматически привязываем его к текущему пользователю (для покупателей)"""
        if not change: 
            if is_buyer_user(request):
                obj.user = request.user
        super().save_model(request, obj, form, change)

 
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Ограничиваем выбор пользователя"""
        if db_field.name == "user":
            if is_superuser(request):
                kwargs["queryset"] = User.objects.filter(type='buyer')
            elif is_buyer_user(request):
                # Обычные покупатели  выбирают  себя автоматом
                kwargs["queryset"] = User.objects.filter(id=request.user.id)
                kwargs["initial"] = request.user
                kwargs["disabled"] = True
            
        return super().formfield_for_foreignkey(db_field, request, **kwargs)    


class ConfirmEmailTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'key', 'created_at',)
    readonly_fields = ('user', 'key', 'created_at')
    search_fields = ('user__email', 'key')
    
    def has_module_permission(self, request):
        """Только суперадмины видят токены"""
        return is_superuser(request)
    
    def has_add_permission(self, request):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False


class MyAdminSite(AdminSite):

    def get_formatted_header(self, request):
        """
        Формируем заголовок с именем пользователя
        """
        base_header = "Панель управления интернет-магазином"
        
        if request.user.is_authenticated:
            # Получаем имя пользователя
            if request.user.first_name and request.user.last_name:
                user_name = f"{request.user.first_name} {request.user.last_name}"
            elif request.user.first_name:
                user_name = request.user.first_name
            else:
                user_name = request.user.email
            
            return f"{base_header} | {user_name}"
        
        return base_header
    
    def each_context(self, request):
        context = super().each_context(request)
        context['site_header'] = self.get_formatted_header(request)
        return context

    
    def has_permission(self, request):
        """
        Переопределяем проверку permissions
        is_staff=True достаточно для входа
        """
        return request.user.is_active and request.user.is_staff
    
    def get_app_list(self, request):
        """
        Кастомизация списка приложений в зависимости от типа пользователя
        """
        # Получаем стандартный список приложений
        app_list = super().get_app_list(request)
        
        # Для неавторизованных пользователей - пустой список
        if not request.user.is_authenticated:
            return []
        
        # Суперадмины видят ВСЁ
        if is_superuser(request):
            return app_list
        
        # Фильтруем модели в приложении backend
        filtered_app_list = []
        
        for app in app_list:
            if app['app_label'] == 'backend':
                app_copy = app.copy()
                app_copy['models'] = []
                
                # Для всех моделей в backend
                for model in app['models']:
                    model_name = model['object_name']
                    
                    # ПОКУПАТЕЛИ видят ВСЕ модели (Shop, Category, Product, ProductInfo, 
                    # Parameter, ProductParameter, Order, OrderItem, Contact)
                    if request.user.type == 'buyer':
                        # Покупатели видят все модели backend
                        app_copy['models'].append(model)
                    
                    # МАГАЗИНЫ видят все модели кроме User и Contact
                    elif is_shop_user(request):
                        if model_name not in ['Contact', 'ConfirmEmailToken']:
                            app_copy['models'].append(model)
                
                # Добавляем приложение только если в нем есть модели
                if app_copy['models']:
                    filtered_app_list.append(app_copy)
        
        return filtered_app_list


# Создаем кастомный сайт админки
admin_site = MyAdminSite(name='myadmin')

# Регистрируем все модели на кастомном сайте
admin_site.register(User, CustomUserAdmin)
admin_site.register(Shop, ShopAdmin)
admin_site.register(Category, CategoryAdmin)
admin_site.register(Product, ProductAdmin)
admin_site.register(ProductInfo, ProductInfoAdmin)
admin_site.register(Parameter, ParameterAdmin)
admin_site.register(ProductParameter, ProductParameterAdmin)
admin_site.register(Order, OrderAdmin)
admin_site.register(OrderItem, OrderItemAdmin)
admin_site.register(Contact, ContactAdmin)
admin_site.register(ConfirmEmailToken, ConfirmEmailTokenAdmin)

# Заменяем стандартный admin.site на кастомный
admin.site = admin_site