from gpubench import run_matmul


def test_matmul_is_correct_on_the_gpu(tmp_path):
    run = run_matmul(tmp_path)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "bad=0" in run.stdout
