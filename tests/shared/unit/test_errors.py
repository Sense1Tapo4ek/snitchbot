"""Unit tests for the shared error hierarchy (Task 1.1)."""

from snitchbot.shared.generics.errors import (
    AdapterError,
    AppError,
    DomainError,
    LayerError,
    PortError,
)


class TestErrorHierarchy:
    def test_layererror_is_exception_subclass(self):
        """
        Given the LayerError base,
        When inspecting its MRO,
        Then it inherits from the built-in Exception.
        """
        assert issubclass(LayerError, Exception)

    def test_domain_error_inherits_layer_error(self):
        """Given DomainError, When checked, Then it is a LayerError subclass."""
        assert issubclass(DomainError, LayerError)

    def test_app_error_inherits_layer_error(self):
        """Given AppError, When checked, Then it is a LayerError subclass."""
        assert issubclass(AppError, LayerError)

    def test_port_error_inherits_layer_error(self):
        """Given PortError, When checked, Then it is a LayerError subclass."""
        assert issubclass(PortError, LayerError)

    def test_adapter_error_inherits_layer_error(self):
        """Given AdapterError, When checked, Then it is a LayerError subclass."""
        assert issubclass(AdapterError, LayerError)

    def test_errors_not_dataclasses(self):
        """
        Given the error classes,
        When checking for dataclass metadata,
        Then none expose `__dataclass_fields__` (classic __init__ style).
        """
        for cls in (LayerError, DomainError, AppError, PortError, AdapterError):
            assert not hasattr(cls, "__dataclass_fields__"), (
                f"{cls.__name__} must not be a dataclass"
            )

    def test_subclasses_disjoint(self):
        """
        Given the four sibling layer errors,
        When comparing pairwise,
        Then none is a subclass of another (only LayerError unites them).
        """
        siblings = (DomainError, AppError, PortError, AdapterError)
        for a in siblings:
            for b in siblings:
                if a is b:
                    continue
                assert not issubclass(a, b), f"{a.__name__} must not inherit from {b.__name__}"

    def test_layer_error_accepts_message(self):
        """
        Given LayerError instantiated with a message,
        When converting it to str,
        Then the message is preserved.
        """
        exc = LayerError("boom")
        assert str(exc) == "boom"

    def test_subclasses_accept_message(self):
        """Each layer-error subclass also preserves its message through str()."""
        for cls in (DomainError, AppError, PortError, AdapterError):
            assert str(cls("bang")) == "bang"

    def test_can_catch_subclass_as_layer_error(self):
        """Catching LayerError must catch every subclass."""
        for cls in (DomainError, AppError, PortError, AdapterError):
            try:
                raise cls("x")
            except LayerError as caught:
                assert isinstance(caught, cls)
            else:
                raise AssertionError("LayerError did not catch subclass")
