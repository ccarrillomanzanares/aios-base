################################################################################
#
# AIOS — ajustes a paquetes de Buildroot
#
# Buildroot incluye este fichero DESPUÉS de package/*/*.mk, y las opciones de
# cmake (<PKG>_CONF_OPTS) se expanden al ejecutar la receta, así que lo que se
# añade aquí sí llega al build sin copiar el paquete.
#
################################################################################

include $(sort $(wildcard $(BR2_EXTERNAL_AIOS_PATH)/package/*/*.mk))

# llama.cpp con TODAS las variantes de CPU x86 en una sola imagen.
# El sistema se compila para x86-64 base (corre en cualquier PC de 64 bits) y
# ggml elige en tiempo de ejecución la variante más rápida que soporte la CPU:
# AVX1 en un AMD A8 antiguo, AVX-512 en un i5-1035G1. Sin esto habría que
# elegir entre lento en todas partes o SIGILL en las CPU viejas.
# Las bibliotecas de backend (libggml-cpu-*.so) se instalan junto a los
# binarios; GGML_BACKEND_DIR fija dónde las busca llama-server.
LLAMA_CPP_CONF_OPTS += \
	-DGGML_NATIVE=OFF \
	-DGGML_BACKEND_DL=ON \
	-DGGML_CPU_ALL_VARIANTS=ON \
	-DGGML_BACKEND_DIR=/usr/lib/ggml
