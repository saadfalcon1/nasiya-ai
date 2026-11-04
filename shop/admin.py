from django.contrib import admin

from .models import (Customer, MessageLog, PendingAction, Product, Promise, Shop, Transaction,
                     TransactionItem)


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "telegram_id", "created_at")


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "note", "phone", "credit_limit", "telegram_chat_id", "shop", "balance")
    search_fields = ("name", "note", "phone")
    list_filter = ("shop",)

    def get_queryset(self, request):
        return super().get_queryset(request).with_balance()

    @admin.display(ordering="balance", description="Qarz")
    def balance(self, obj):
        return obj.balance


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "unit", "cost_price", "sell_price", "stock", "shop")
    search_fields = ("name",)


class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "customer", "amount", "customer_status", "source_type", "shop")
    list_filter = ("kind", "customer_status", "source_type", "shop")
    inlines = [TransactionItemInline]


@admin.register(PendingAction)
class PendingActionAdmin(admin.ModelAdmin):
    list_display = ("id", "shop", "status", "source_type", "created_at")
    list_filter = ("status",)


@admin.register(Promise)
class PromiseAdmin(admin.ModelAdmin):
    list_display = ("customer", "amount", "due_date", "status", "reminded_at", "shop")
    list_filter = ("status",)


@admin.register(MessageLog)
class MessageLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "customer", "channel", "ok", "shop")
    list_filter = ("channel", "ok")
