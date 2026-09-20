import sys

if sys.argv[1:2] == ["serve"]:
    from dengue_link.server import make_server

    httpd = make_server()
    print("Dengue Link live at http://127.0.0.1:8000 — data is fetched fresh once every 24 hours")
    httpd.serve_forever()
else:
    from dengue_link.pipeline import run

    out, model, accuracy = run()
    print(out)
    if model:
        print("model", {k: round(float(v), 3) for k, v in model.items()})
        print("backtest", accuracy)
