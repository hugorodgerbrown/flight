"""The form for following a flight."""

from django import forms

from apps.alerts.follows import NotAFlightNumber, clean_number


class FollowForm(forms.Form):
    """A flight number to follow, such as BA117."""

    flight = forms.CharField(max_length=12)

    def clean_flight(self) -> str:
        """Return the number upper-cased without spaces, or say what a flight number looks like."""
        try:
            return clean_number(self.cleaned_data["flight"])
        except NotAFlightNumber:
            raise forms.ValidationError(
                "Enter a flight number, such as BA117 or EZY8812."
            ) from None
