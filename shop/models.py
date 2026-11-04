import secrets
from decimal import Decimal

from django.db import models
from django.db.models import Case, DecimalField, F, Sum, Value, When
from django.db.models.functions import Coalesce

MONEY = dict(max_digits=14, decimal_places=2)


def new_link_token() -> str:
    return secrets.token_urlsafe(9)


class Shop(models.Model):
    """Har bir do'konchi = bitta Telegram foydalanuvchisi."""

    telegram_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    lang = models.CharField(max_length=2, default="uz", choices=[("uz", "O'zbekcha"), ("ru", "Русский"), ("en", "English")])
    brief_hour = models.PositiveSmallIntegerField(default=8, help_text="Ertalabki brifing soati (Toshkent)")
    last_brief_date = models.DateField(null=True, blank=True)
    auto_remind = models.BooleanField(default=True, help_text="Qarzdorlarga avtomatik eslatma")
    remind_hour = models.PositiveSmallIntegerField(default=10, help_text="Avto-eslatma soati (Toshkent)")
    last_auto_remind_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name or "Do'kon"


class CustomerQuerySet(models.QuerySet):
    def with_balance(self):
        """balance = nasiyalar yig'indisi - to'lovlar yig'indisi."""
        signed = Case(
            When(transactions__kind="nasiya", then=F("transactions__amount")),
            When(transactions__kind="tolov", then=-F("transactions__amount")),
            default=Value(Decimal("0")),
            output_field=DecimalField(**MONEY),
        )
        return self.annotate(
            balance=Coalesce(Sum(signed), Value(Decimal("0")), output_field=DecimalField(**MONEY))
        )


class Customer(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="customers")
    name = models.CharField(max_length=200)
    note = models.CharField(max_length=200, blank=True, help_text="Ajratish uchun: 'Chilonzor', 'yosh' va h.k.")
    phone = models.CharField(max_length=20, blank=True, help_text="998901234567 ko'rinishida")
    telegram_chat_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    link_token = models.CharField(max_length=20, unique=True, default=new_link_token)
    credit_limit = models.DecimalField(**MONEY, null=True, blank=True)
    lang = models.CharField(max_length=2, blank=True, help_text="Bo'sh = do'kon tili")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CustomerQuerySet.as_manager()

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.note})" if self.note else self.name


class Product(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="products")
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=20, blank=True)
    sell_price = models.DecimalField(**MONEY, null=True, blank=True, help_text="Oxirgi sotuv narxi")
    cost_price = models.DecimalField(**MONEY, null=True, blank=True, help_text="Oxirgi kirim (tannarx)")
    stock = models.DecimalField(max_digits=14, decimal_places=3, default=0)

    class Meta:
        unique_together = [("shop", "name")]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Transaction(models.Model):
    class Kind(models.TextChoices):
        NASIYA = "nasiya", "Nasiya (qarzga oldi)"
        TOLOV = "tolov", "To'lov (qarzni to'ladi)"
        SOTUV = "sotuv", "Naqd savdo"
        KIRIM = "kirim", "Kirim (tovar keldi)"

    class Source(models.TextChoices):
        TEXT = "text", "Matn"
        VOICE = "voice", "Ovoz"
        PHOTO = "photo", "Rasm"

    class CustomerStatus(models.TextChoices):
        NONE = "", "—"
        CONFIRMED = "confirmed", "Mijoz tasdiqladi"
        DISPUTED = "disputed", "Mijoz rad etdi"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="transactions")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="transactions")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.DecimalField(**MONEY, default=0)
    source_type = models.CharField(max_length=10, choices=Source.choices, default=Source.TEXT)
    source_text = models.TextField(blank=True, help_text="Asl gap yoki transkripsiya — tekshirish uchun")
    customer_status = models.CharField(max_length=10, choices=CustomerStatus.choices, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} — {self.customer or '-'}"


class TransactionItem(models.Model):
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="tx_items")
    qty = models.DecimalField(max_digits=14, decimal_places=3)
    unit = models.CharField(max_length=20, blank=True)
    price = models.DecimalField(**MONEY, null=True, blank=True)
    cost = models.DecimalField(**MONEY, null=True, blank=True, help_text="Sotuv paytidagi tannarx (foyda uchun)")
    total = models.DecimalField(**MONEY, default=0)


class Promise(models.Model):
    """Mijozning to'lov va'dasi: 'Akmal aka juma kuni beraman dedi'."""

    class Status(models.TextChoices):
        OPEN = "open", "Kutilmoqda"
        KEPT = "kept", "Bajarildi"
        BROKEN = "broken", "Bajarilmadi"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="promises")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="promises")
    amount = models.DecimalField(**MONEY, null=True, blank=True, help_text="Bo'sh = butun qarz")
    due_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    source_text = models.TextField(blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["due_date"]


class MessageLog(models.Model):
    """Mijozga yuborilgan har bir eslatma — kim, qachon, qaysi kanal."""

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="messages")
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="messages")
    channel = models.CharField(max_length=10)  # telegram | sms
    text = models.TextField()
    ok = models.BooleanField(default=False)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PendingAction(models.Model):
    """AI ajratgan, lekin do'konchi hali tasdiqlamagan yozuv."""

    class Status(models.TextChoices):
        PENDING = "pending", "Kutilmoqda"
        CONFIRMED = "confirmed", "Tasdiqlandi"
        CANCELLED = "cancelled", "Bekor qilindi"

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="pending_actions")
    payload = models.JSONField()
    source_type = models.CharField(max_length=10, default="text")
    source_text = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)


class KnownContact(models.Model):
    """Botga o'z raqamini yuborgan Telegram foydalanuvchisi: telefon -> chat_id.
    Do'konchi keyinroq shu raqamli mijozni kiritsa ham, u avtomatik ulanadi."""

    phone = models.CharField(max_length=20, unique=True)
    chat_id = models.BigIntegerField()
    name = models.CharField(max_length=200, blank=True)
    lang = models.CharField(max_length=2, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ShelfAudit(models.Model):
    """Javon surati bo'yicha AI sanog'i (ertalab / kechqurun)."""

    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="shelf_audits")
    photo_file_id = models.CharField(max_length=300, blank=True)
    empty_spots = models.PositiveSmallIntegerField(default=0)
    observations = models.JSONField(default=list, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]


class ShelfItem(models.Model):
    audit = models.ForeignKey(ShelfAudit, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name="shelf_items")
    name = models.CharField(max_length=200)
    count = models.DecimalField(max_digits=10, decimal_places=1)
    confidence = models.CharField(max_length=10, blank=True)
