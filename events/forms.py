from zoneinfo import available_timezones

from django import forms


class EventForm(forms.Form):
    name = forms.CharField(max_length=200)
    venue_name = forms.CharField(max_length=200)
    address_line1 = forms.CharField(max_length=200, label="Address")
    address_line2 = forms.CharField(max_length=200, required=False, label="Address line 2")
    locality = forms.CharField(max_length=120)
    region = forms.CharField(max_length=120, required=False)
    postal_code = forms.CharField(max_length=32)
    country = forms.CharField(max_length=80)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    contact_name = forms.CharField(max_length=200, required=False)
    contact_email = forms.EmailField(required=False)
    contact_phone = forms.CharField(max_length=40, required=False)
    timezone = forms.ChoiceField(choices=[])
    starts_at = forms.CharField(label="Starts")
    ends_at = forms.CharField(label="Ends")
    doors_open_at = forms.CharField(required=False, label="Doors open")
    initial_table_count = forms.IntegerField(min_value=0, initial=0)
    default_seats_per_table = forms.IntegerField(min_value=1, initial=8)
    accessibility_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    internal_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
    logo = forms.FileField(required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        zones = sorted(available_timezones())
        self.fields["timezone"].choices = [(zone, zone) for zone in zones]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "control")
