#!/bin/bash

cd transformers/examples/pytorch/text-classification/

# Install required packages
pip install datasets

# Task and Model
export TASK_NAME=mnli
export MODEL_NAME=microsoft/deberta-v3-large
export OUTPUT_DIR="ds_results"

# Training setup
export NUM_GPUS=1              # Set this to 1 or more depending on your hardware
export BATCH_SIZE=8            # Reduce batch size if you hit memory limits

# Run the fine-tuning
python -m torch.distributed.launch --nproc_per_node=$NUM_GPUS \
  run_glue.py \
  --model_name_or_path $MODEL_NAME \
  --task_name $TASK_NAME \
  --do_train \
  --do_eval \
  --evaluation_strategy steps \
  --save_strategy steps \
  --save_steps 1000 \
  --max_seq_length 256 \
  --learning_rate 6e-6 \
  --per_device_train_batch_size $BATCH_SIZE \
  --per_device_eval_batch_size $BATCH_SIZE \
  --num_train_epochs 2 \
  --warmup_steps 50 \
  --output_dir $OUTPUT_DIR \
  --overwrite_output_dir \
  --logging_dir $OUTPUT_DIR \
  --logging_steps 500 \
  --fp16 \
  --report_to none
