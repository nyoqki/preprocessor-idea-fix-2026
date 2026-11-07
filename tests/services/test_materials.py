from yasno.ai.fakes import FakeChat, FakeOcr, FakeVision
from yasno.ai.tutor import Tutor
from yasno.ai.types import ProviderError
from yasno.services.materials import recognize_text


async def test_material_uses_vision_when_ocr_is_unavailable() -> None:
    tutor = Tutor(FakeChat(), FakeVision(), FakeOcr(ProviderError("ocr", "down")))
    text = await recognize_text(tutor, b"photo", "image/jpeg")
    assert "2x + 3 = 7" in text
