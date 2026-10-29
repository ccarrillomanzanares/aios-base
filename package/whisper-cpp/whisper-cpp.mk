################################################################################
#
# whisper-cpp — reconocimiento de voz local
#
################################################################################

WHISPER_CPP_VERSION = 1.9.5
WHISPER_CPP_SOURCE = v$(WHISPER_CPP_VERSION).tar.gz
WHISPER_CPP_SITE = https://github.com/ggml-org/whisper.cpp/archive/refs/tags
WHISPER_CPP_LICENSE = MIT
WHISPER_CPP_LICENSE_FILES = LICENSE

# Como llama.cpp: x86-64 base y ggml elige la variante de CPU al arrancar
# (AVX1 ... AVX-512), así una sola imagen va rápida y sin SIGILL en todas.
# Prefijo propio: su ggml (0.26) no es el de llama.cpp (0.9.x).
WHISPER_CPP_CONF_OPTS = \
	-DCMAKE_INSTALL_PREFIX=/opt/whisper \
	-DCMAKE_INSTALL_RPATH=/opt/whisper/lib \
	-DBUILD_SHARED_LIBS=ON \
	-DGGML_NATIVE=OFF \
	-DGGML_BACKEND_DL=ON \
	-DGGML_CPU_ALL_VARIANTS=ON \
	-DGGML_BACKEND_DIR=/opt/whisper/lib \
	-DGGML_OPENMP=OFF \
	-DWHISPER_BUILD_TESTS=OFF \
	-DWHISPER_BUILD_EXAMPLES=ON \
	-DWHISPER_BUILD_SERVER=OFF \
	-DWHISPER_SDL2=OFF \
	-DWHISPER_CURL=OFF

# Solo whisper-cli y sus bibliotecas; las variantes de CPU, junto a ellas
define WHISPER_CPP_TRIM_INSTALL
	rm -rf $(TARGET_DIR)/opt/whisper/include $(TARGET_DIR)/opt/whisper/lib/cmake \
		$(TARGET_DIR)/opt/whisper/lib/pkgconfig
	find $(TARGET_DIR)/opt/whisper/bin -type f ! -name whisper-cli -delete
	find $(TARGET_DIR)/opt/whisper -name 'libggml-cpu*.so' ! -path '*/lib/*' \
		-exec mv -f {} $(TARGET_DIR)/opt/whisper/lib/ \;
endef
WHISPER_CPP_POST_INSTALL_TARGET_HOOKS += WHISPER_CPP_TRIM_INSTALL

$(eval $(cmake-package))
