#!/usr/bin/env python3
"""
Script para optimizar modelos YOLO para Jetson Nano
Exporta a TensorRT y ONNX
"""

import os
import sys
import argparse
import logging
from pathlib import Path

try:
    from ultralytics import YOLO
    import torch
except ImportError:
    print("ERROR: Dependencias no instaladas")
    print("Ejecuta: pip install ultralytics torch")
    sys.exit(1)


def export_to_tensorrt(model_path, half=True, workspace=4):
    """
    Exportar modelo a TensorRT
    
    Args:
        model_path: Ruta al modelo .pt
        half: Usar FP16
        workspace: Tamaño de workspace en GB
    """
    print("=" * 60)
    print("EXPORTANDO A TENSORRT")
    print("=" * 60)
    print(f"Modelo: {model_path}")
    print(f"Precisión: {'FP16' if half else 'FP32'}")
    print(f"Workspace: {workspace} GB")
    print()
    
    if not torch.cuda.is_available():
        print("ERROR: CUDA no está disponible")
        print("TensorRT requiere una GPU NVIDIA")
        return None
    
    try:
        # Cargar modelo
        model = YOLO(model_path)
        
        print("Exportando a TensorRT...")
        print("(Esto puede tomar varios minutos)")
        
        # Exportar
        engine_path = model.export(
            format='engine',
            half=half,
            workspace=workspace,
            verbose=True
        )
        
        print(f"\n✓ Modelo exportado exitosamente")
        print(f"  Ruta: {engine_path}")
        
        if os.path.exists(engine_path):
            size_mb = os.path.getsize(engine_path) / (1024 * 1024)
            print(f"  Tamaño: {size_mb:.2f} MB")
        
        return engine_path
        
    except Exception as e:
        print(f"\n✗ Error exportando a TensorRT: {e}")
        print("\nPosibles soluciones:")
        print("1. Asegurar que TensorRT esté instalado")
        print("2. Verificar compatibilidad de CUDA")
        print("3. Verificar memoria GPU suficiente")
        return None


def export_to_onnx(model_path, opset=12, simplify=True):
    """
    Exportar modelo a ONNX
    
    Args:
        model_path: Ruta al modelo .pt
        opset: Versión de opset ONNX
        simplify: Simplificar modelo
    """
    print("=" * 60)
    print("EXPORTANDO A ONNX")
    print("=" * 60)
    print(f"Modelo: {model_path}")
    print(f"Opset: {opset}")
    print(f"Simplificar: {simplify}")
    print()
    
    try:
        # Cargar modelo
        model = YOLO(model_path)
        
        print("Exportando a ONNX...")
        
        # Exportar
        onnx_path = model.export(
            format='onnx',
            opset=opset,
            simplify=simplify
        )
        
        print(f"\n✓ Modelo exportado exitosamente")
        print(f"  Ruta: {onnx_path}")
        
        if os.path.exists(onnx_path):
            size_mb = os.path.getsize(onnx_path) / (1024 * 1024)
            print(f"  Tamaño: {size_mb:.2f} MB")
        
        return onnx_path
        
    except Exception as e:
        print(f"\n✗ Error exportando a ONNX: {e}")
        return None


def benchmark_model(model_path, imgsz=640, data='coco8.yaml'):
    """
    Hacer benchmark del modelo
    
    Args:
        model_path: Ruta al modelo
        imgsz: Tamaño de imagen
        data: Dataset para validación
    """
    print("=" * 60)
    print("BENCHMARK DEL MODELO")
    print("=" * 60)
    print(f"Modelo: {model_path}")
    print(f"Tamaño: {imgsz}")
    print()
    
    try:
        model = YOLO(model_path)
        
        print("Ejecutando benchmark...")
        
        # Benchmark de velocidad
        results = model.benchmark(
            imgsz=imgsz,
            half=True,
            device=0 if torch.cuda.is_available() else 'cpu',
            verbose=True
        )
        
        print("\n✓ Benchmark completado")
        
        return results
        
    except Exception as e:
        print(f"\n✗ Error en benchmark: {e}")
        return None


def optimize_for_jetson(model_path):
    """
    Pipeline completo de optimización para Jetson Nano
    
    Args:
        model_path: Ruta al modelo .pt
    """
    print("=" * 70)
    print(" OPTIMIZACIÓN COMPLETA PARA JETSON NANO")
    print("=" * 70)
    print()
    
    results = {
        'tensorrt': None,
        'onnx': None,
        'benchmark': None
    }
    
    # 1. Exportar a ONNX (siempre funciona)
    print("\n[1/3] Exportando a ONNX...")
    results['onnx'] = export_to_onnx(model_path)
    
    # 2. Exportar a TensorRT (solo si CUDA disponible)
    if torch.cuda.is_available():
        print("\n[2/3] Exportando a TensorRT...")
        results['tensorrt'] = export_to_tensorrt(
            model_path,
            half=True,  # FP16 para Jetson Nano
            workspace=2  # 2GB para Jetson Nano 4GB
        )
    else:
        print("\n[2/3] SALTADO - CUDA no disponible")
    
    # 3. Benchmark
    print("\n[3/3] Ejecutando benchmark...")
    results['benchmark'] = benchmark_model(model_path, imgsz=640)
    
    # Resumen
    print("\n" + "=" * 70)
    print(" RESUMEN DE OPTIMIZACIÓN")
    print("=" * 70)
    
    if results['onnx']:
        print(f"✓ ONNX: {results['onnx']}")
    else:
        print("✗ ONNX: Falló")
    
    if results['tensorrt']:
        print(f"✓ TensorRT: {results['tensorrt']}")
    else:
        print("✗ TensorRT: No disponible o falló")
    
    print("\nRecomendaciones para Jetson Nano:")
    print("1. Usar TensorRT FP16 para máximo rendimiento")
    print("2. Configurar: sudo nvpmodel -m 0 && sudo jetson_clocks")
    print("3. Usar input_size=416 o 320 para mayor velocidad")
    print("4. Habilitar skip_frames=1 para ~2x FPS")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description='Optimizar modelos YOLO para inferencia'
    )
    
    parser.add_argument(
        '--model',
        type=str,
        required=True,
        help='Ruta al modelo .pt'
    )
    
    parser.add_argument(
        '--format',
        type=str,
        choices=['tensorrt', 'onnx', 'both'],
        default='both',
        help='Formato de exportación'
    )
    
    parser.add_argument(
        '--half',
        action='store_true',
        help='Usar precisión FP16'
    )
    
    parser.add_argument(
        '--jetson',
        action='store_true',
        help='Optimización completa para Jetson Nano'
    )
    
    parser.add_argument(
        '--benchmark',
        action='store_true',
        help='Ejecutar benchmark del modelo'
    )
    
    args = parser.parse_args()
    
    # Verificar que el modelo existe
    if not os.path.exists(args.model):
        print(f"ERROR: Modelo no encontrado: {args.model}")
        sys.exit(1)
    
    # Optimización para Jetson (pipeline completo)
    if args.jetson:
        optimize_for_jetson(args.model)
        return
    
    # Exportaciones individuales
    if args.format in ['tensorrt', 'both']:
        export_to_tensorrt(args.model, half=args.half)
    
    if args.format in ['onnx', 'both']:
        export_to_onnx(args.model)
    
    # Benchmark
    if args.benchmark:
        benchmark_model(args.model)


if __name__ == '__main__':
    main()
