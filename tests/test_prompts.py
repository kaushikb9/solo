import pytest


@pytest.fixture
def fake_prompts_dir(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "classifier.md").write_text("Classify: {entry}")
    (prompts / "noargs.md").write_text("Just text, no vars")
    monkeypatch.setattr("solo.prompts.PROMPTS_DIR", prompts)
    return prompts


class TestLoad:
    def test_load_returns_file_contents(self, fake_prompts_dir):
        from solo.prompts import load

        assert load("classifier") == "Classify: {entry}"

    def test_load_missing_file_raises(self, fake_prompts_dir):
        from solo.prompts import load

        with pytest.raises(FileNotFoundError):
            load("nonexistent")


class TestRender:
    def test_render_substitutes_vars(self, fake_prompts_dir):
        from solo.prompts import render

        assert render("classifier", entry="learn rust") == "Classify: learn rust"

    def test_render_with_no_vars_works(self, fake_prompts_dir):
        from solo.prompts import render

        assert render("noargs") == "Just text, no vars"

    def test_render_missing_var_raises(self, fake_prompts_dir):
        from solo.prompts import render

        with pytest.raises(KeyError):
            render("classifier")  # template needs {entry}, none passed
