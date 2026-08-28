#!/usr/bin/env python3
"""
Script de prueba para verificar instalación y funcionamiento
"""

import sys
import os

def test_imports():
    """Verificar que todas las dependencias están instaladas"""
    print("=" * 60)
    print("TEST 1: VERIFICANDO DEPENDENCIAS")
    print("=" * 60)
    
    dependencies = [
        ('cv2', 'opencv-python'),
        ('numpy', 'numpy'),
        ('torch', 'torch'),
        ('ultralytics', 'ultralytics'),
        ('yaml', 'pyyaml'),
        ('scipy', 'scipy'),
        ('filterpy', 'filterpy'),
        ('matplotlib', 'matplotlib'),
        ('pandas', 'pandas'),
    ]
    
    missing = []
    
    for module, package in dependencies:
        try:
            __import__(module)
            print(f"  ✓ {package}")
        except ImportError:
            print(f"  ✗ {package} - NO INSTALADO")
            missing.append(package)
    
    if missing:
        print(f"\nERROR: Faltan {len(missing)} dependencias")
        print("Instalar con: pip install " + " ".join(missing))
        return False
    
    print("\n✓ Todas las dependencias están instaladas")
    return True


def test_cuda():
    """Verificar disponibilidad de CUDA"""
    print("\n" + "=" * 60)
    print("TEST 2: VERIFICANDO CUDA")
    print("=" * 60)
    
    try:
        import torch
        
        if torch.cuda.is_available():
            print("  ✓ CUDA disponible")
            print(f"  GPU: {torch.cuda.get_device_name(0)}")
            print(f"  Memoria: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
            print(f"  CUDA Version: {torch.version.cuda}")
            return True
        else:
            print("  ! CUDA no disponible - usando CPU")
            print("  (El sistema funcionará pero será más lento)")
            return True
    except Exception as e:
        print(f"  ✗ Error verificando CUDA: {e}")
        return False


def test_yolo_model():
    """Verificar que YOLO funciona"""
    print("\n" + "=" * 60)
    print("TEST 3: VERIFICANDO YOLO")
    print("=" * 60)
    
    try:
        from ultralytics import YOLO
        import numpy as np
        
        print("  Cargando modelo YOLOv8n...")
        model = YOLO('yolov8n.pt')
        
        print("  Generando imagen de prueba...")
        test_image = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
        
        print("  Ejecutando inferencia...")
        results = model.predict(test_image, verbose=False)
        
        print("  ✓ YOLO funcionando correctamente")
        return True
        
    except Exception as e:
        print(f"  ✗ Error en YOLO: {e}")
        return False


def test_modules():
    """Verificar módulos del proyecto"""
    print("\n" + "=" * 60)
    print("TEST 4: VERIFICANDO MÓDULOS DEL PROYECTO")
    print("=" * 60)
    
    modules = [
        'src.detector',
        'src.tracker',
        'src.counter',
        'src.visualizer',
        'src.video_processor',
        'src.reporter',
        'src.utils'
    ]
    
    all_ok = True
    
    for module in modules:
        try:
            __import__(module)
            print(f"  ✓ {module}")
        except ImportError as e:
            print(f"  ✗ {module} - ERROR: {e}")
            all_ok = False
    
    if all_ok:
        print("\n✓ Todos los módulos se cargan correctamente")
    else:
        print("\n✗ Algunos módulos tienen errores")
    
    return all_ok


def test_video_processing():
    """Prueba rápida de procesamiento"""
    print("\n" + "=" * 60)
    print("TEST 5: PRUEBA DE PROCESAMIENTO")
    print("=" * 60)
    
    try:
        import cv2
        import numpy as np
        from src.detector import VehicleDetector
        from src.tracker import VehicleTracker
        from src.counter import BidirectionalCounter
        
        print("  Inicializando componentes...")
        
        detector = VehicleDetector(
            model_path='yolov8n.pt',
            confidence_threshold=0.4
        )
        
        tracker = VehicleTracker()
        
        counter = BidirectionalCounter(line_type='horizontal')
        counter.set_counting_line(
            line_type='horizontal',
            y=320,
            frame_shape=(640, 640)
        )
        
        print("  Generando frame de prueba...")
        test_frame = np.random.randint(0, 255, (640, 640, 3), dtype=np.uint8)
        
        print("  Ejecutando detección...")
        detections, _ = detector.detect(test_frame)
        
        print("  Ejecutando tracking...")
        tracks = tracker.update(detections)
        
        print("  Ejecutando conteo...")
        crossings = counter.update(tracks)
        
        print("  ✓ Pipeline de procesamiento funciona")
        print(f"    Detecciones: {len(detections)}")
        print(f"    Tracks: {len(tracks)}")
        
        return True
        
    except Exception as e:
        print(f"  ✗ Error en procesamiento: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config_files():
    """Verificar archivos de configuración"""
    print("\n" + "=" * 60)
    print("TEST 6: VERIFICANDO ARCHIVOS DE CONFIGURACIÓN")
    print("=" * 60)
    
    config_files = [
        'configs/default_config.yaml',
        'configs/jetson_optimized.yaml'
    ]
    
    all_ok = True
    
    for config_file in config_files:
        if os.path.exists(config_file):
            print(f"  ✓ {config_file}")
            
            # Intentar cargar
            try:
                import yaml
                with open(config_file, 'r') as f:
                    yaml.safe_load(f)
                print(f"    → Válido")
            except Exception as e:
                print(f"    → ERROR parseando: {e}")
                all_ok = False
        else:
            print(f"  ✗ {config_file} - NO ENCONTRADO")
            all_ok = False
    
    if all_ok:
        print("\n✓ Todos los archivos de configuración OK")
    
    return all_ok


def main():
    """Ejecutar todos los tests"""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "TEST DEL SISTEMA DE AFORO VEHICULAR" + " " * 12 + "║")
    print("╚" + "=" * 58 + "╝")
    print()
    
    results = {
        'Dependencias': test_imports(),
        'CUDA': test_cuda(),
        'YOLO': test_yolo_model(),
        'Módulos': test_modules(),
        'Procesamiento': test_video_processing(),
        'Configuración': test_config_files()
    }
    
    # Resumen
    print("\n" + "=" * 60)
    print("RESUMEN DE TESTS")
    print("=" * 60)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {test_name:<20} {status}")
    
    passed = sum(results.values())
    total = len(results)
    
    print("\n" + "=" * 60)
    print(f"RESULTADO: {passed}/{total} tests pasados")
    print("=" * 60)
    
    if passed == total:
        print("\n✓ Sistema listo para usar!")
        print("\nPróximos pasos:")
        print("1. Coloca un video en la carpeta 'input/'")
        print("2. Ejecuta: python main.py --video input/tu_video.mp4")
        return 0
    else:
        print("\n✗ Algunos tests fallaron")
        print("Revisar errores arriba y corregir antes de usar el sistema")
        return 1


if __name__ == '__main__':
    sys.exit(main())
