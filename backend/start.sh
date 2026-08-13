#!/bin/bash
#gn121daEJA2Um7WpwDyqC2HzGpbKtZ9lIIFvzqfDsWQ
export LEGADOHUB_ADMIN_BASE_URL=https://hub.xzaiweb.cn
export LEGADOHUB_PUBLIC_BASE_URL=https://hub.xzaiweb.cn
export LEGADOHUB_ADMIN_ALLOWED_HOSTS=hub.xzaiweb.cn
export LEGADOHUB_ALLOWED_HOSTS=hub.xzaiweb.cn
export LEGADOHUB_TRUSTED_PROXIES=127.0.0.1/32
export LEGADOHUB_ADMIN_TRUSTED_PROXIES=127.0.0.1/32
python -m app.server --host 127.0.0.1 --public-port 8765 --admin-port 8766