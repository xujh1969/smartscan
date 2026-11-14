def test_package_exposes_version():
    import smartscan

    assert isinstance(smartscan.__version__, str) and smartscan.__version__
