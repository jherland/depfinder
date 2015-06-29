def adjust_env(env, adjustments):
    for k, v in adjustments.items():
        if v is None:
            if k in env:
                del env[k]
        else:
            env[k] = v
