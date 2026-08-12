from rest_framework import serializers


class NotifyOnPromocodeSerializer(serializers.Serializer):
    notify_on_promocode = serializers.BooleanField()
