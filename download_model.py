#!/usr/bin/env python3
"""
Script para descargar modelos YOLO
"""

import os
import sys
import logging
from pathlib import Path

try:
    from ultralytics import YOLO
except ImportError:
    print("ERROR: ultralytics no está instalado")
    print("Ejecuta: pip install ultralytics")
    sys.exit(1)


def download_model(model_name='yolov8n.pt', models_dir='models'):
    """
    Descargar modelo YOLO
    
    Args:
        model_name: Nombre del modelo (yolov8n, yolov8s, yolov8m, yolov8l, yolov8x)
        models_dir: Directorio donde guardar modelos
    """
    # Crear directorio si no existe
    os.makedirs(models_dir, exist_ok=True)
    
    model_path = os.path.join(models_dir, model_name)
    
    print("=" * 60)
    print(f"DESCARGA DE MODELO YOLO")
    print("=" * 60)
    print(f"Modelo: {model_name}")
    print(f"Destino: {model_path}")
    print()
    
    # Verificar si ya existe
    if os.path.exists(model_path):
        print(f"✓ El modelo ya existe: {model_path}")
        
        response = input("\n¿Descargar de nuevo? (s/n): ")
        if response.lower() != 's':
            print("Descarga cancelada")
            return model_path
    
    try:
        print("\nDescargando modelo...")
        print("(Esto puede tomar varios minutos)")
        
        # YOLO descarga automáticamente si no existe
        model = YOLO(model_name)
        
        # Mover a directorio de modelos
        source = model_name
        if os.path.exists(source) and not os.path.exists(model_path):
            import shutil
            shutil.move(source, model_path)
        
        print(f"\n✓ Modelo descargado exitosamente: {model_path}")
        
        # Información del modelo
        print("\nInformación del Modelo:")
        print(f"  Nombre: {model_name}")
        print(f"  Tamaño: {os.path.getsize(model_path) / (1024*1024):.2f} MB")
        print(f"  Ruta: {os.path.abspath(model_path)}")
        
        return model_path
        
    except Exception as e:
        print(f"\n✗ Error descargando modelo: {e}")
        return None


def download_all_models():
    """Descargar todos los modelos disponibles"""
    models = ['yolov8n.pt', 'yolov8s.pt', 'yolov8m.pt']
    
    print("Descargando todos los modelos...")
    print("Modelos: ", ", ".join(models))
    print()
    
    for model in models:
        print(f"\n{'='*60}")
        download_model(model)
    
    print(f"\n{'='*60}")
    print("Descarga completada")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Descargar modelos YOLO para el sistema de aforo'
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default='yolov8n.pt',
        choices=['yolov8n.pt', 'yolov8s.pt', 'yolov8m.pt', 'yolov8l.pt', 'yolov8x.pt'],
        help='Modelo a descargar'
    )
    
    parser.add_argument(
        '--all',
        action='store_true',
        help='Descargar todos los modelos comunes'
    )
    
    parser.add_argument(
        '--models-dir',
        type=str,
        default='models',
        help='Directorio donde guardar modelos'
    )
    
    args = parser.parse_args()
    
    if args.all:
        download_all_models()
    else:
        download_model(args.model, args.models_dir)


if __name__ == '__main__':
    main()
