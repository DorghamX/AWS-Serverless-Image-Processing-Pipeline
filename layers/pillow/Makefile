# AWS SAM builds this layer when you run `sam build`.
# The target name must be build-<LayerLogicalId> (PillowLayer in template.yaml).
# ARTIFACTS_DIR is provided by SAM and points at the layer build directory.

build-PillowLayer:
	python3 -m pip install \
		--platform manylinux2014_aarch64 \
		--only-binary=:all: \
		--implementation cp \
		--python-version 3.12 \
		--upgrade Pillow \
		--target "$(ARTIFACTS_DIR)/python"
