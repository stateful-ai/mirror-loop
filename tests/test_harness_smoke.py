
def test_llmbench_harness_import():
    from llmbench.harness import main
    assert callable(main)
