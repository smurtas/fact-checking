#!/bin/bash

cd transformers/examples/pytorch/text-classification/

# Install required packages
pip install datasets

# Task and Model
# export CUDA_VISIBLE_DEVICES=0  # Set to the GPU you want to use in Linux
export TASK_NAME=fever
export MODEL_NAME=microsoft/deberta-v3-large
export OUTPUT_DIR="ds_results"
export EPOCHS=3
export TOKENIZERS_PARALLELISM=false
export WANDB_MODE=disabled
# Training setup
export NUM_GPUS=1              # Set this to 1 or more depending on your hardware
export BATCH_SIZE=16            # Reduce batch size if you hit memory limits

# Run the fine-tuning
python -m torch.distributed.launch --nproc_per_node=$NUM_GPUS \
  run_glue.py \
  --model_name_or_path $MODEL_NAME \
  --task_name mnli \
  --do_train \
  --do_eval \
  --learning_rate 6e-6 \
  --max_seq_length 256 \
  --per_device_train_batch_size $BATCH_SIZE \
  --per_device_eval_batch_size $BATCH_SIZE \
  --num_train_epochs $EPOCHS \
  --output_dir $OUTPUT_DIR \
  --overwrite_output_dir \
  --fp16 \
  --max_train_samples 5000 \
  --save_steps 1000


# Check if the output directory exists and contains files
echo "✅ Fine-tuning completato. File generati in:"
ls -lh $OUTPUT_DIR
