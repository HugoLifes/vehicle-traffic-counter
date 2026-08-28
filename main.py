#!/usr/bin/env python3
"""
Sistema de Aforo Vehicular Bidireccional con YOLO
Optimizado para NVIDIA Jetson Nano

Este script principal ejecuta el sistema completo de detección,
tracking y conteo de vehículos desde videos grabados.
"""

import argparse
import os
import sys
import yaml
import logging
from pathlib import Path
import cv2
import numpy as np
from datetime import datetime

from src.detector import VehicleDetector
from src.tracker import VehicleTracker
from src.counter import BidirectionalCounter
from src.video_processor import VideoProcessor, open_video_source, read_with_reconnect
from src.visualizer import Visualizer
from src.reporter import Reporter
from src.utils import setup_logger, check_cuda, get_device_info


def parse_arguments():
    """Parsear argumentos de línea de comandos"""
    parser = argparse.ArgumentParser(
        description='Sistema de Aforo Vehicular Bidireccional con YOLO'
    )
    
    # Argumentos principales
    parser.add_argument(
        '--video',
        type=str,
        default=None,
        help='Ruta al video de entrada (alias de --source, para compatibilidad)'
    )

    parser.add_argument(
        '--source',
        type=str,
        default=None,
        help=(
            'Fuente de video: ruta a archivo, índice de webcam (ej. "0"), '
            'o URL de cámara IP (rtsp://... o http://...)'
        )
    )

    parser.add_argument(
        '--report-interval',
        type=int,
        default=0,
        help=(
            'En fuentes en vivo, generar/actualizar reportes cada N frames '
            '(0 = solo al finalizar)'
        )
    )
    
    parser.add_argument(
        '--config',
        type=str,
        default='configs/default_config.yaml',
        help='Archivo de configuración YAML'
    )
    
    parser.add_argument(
        '--model',
        type=str,
        default='models/yolov8n.pt',
        help='Ruta al modelo YOLO'
    )
    
    parser.add_argument(
        '--output',
        type=str,
        default='results/',
        help='Directorio de salida para resultados'
    )
    
    # Configuración de detección
    parser.add_argument(
        '--confidence',
        type=float,
        default=0.4,
        help='Umbral de confianza para detecciones (0-1)'
    )
    
    parser.add_argument(
        '--iou-threshold',
        type=float,
        default=0.5,
        help='Umbral IoU para NMS'
    )
    
    parser.add_argument(
        '--input-size',
        type=int,
        default=640,
        help='Tamaño de entrada para el modelo'
    )
    
    # Configuración de línea de conteo
    parser.add_argument(
        '--line-y',
        type=int,
        default=None,
        help='Posición Y de la línea de conteo (para línea horizontal)'
    )
    
    parser.add_argument(
        '--direction',
        type=str,
        choices=['horizontal', 'vertical', 'diagonal', 'polygon'],
        default='horizontal',
        help='Tipo de línea de conteo'
    )
    
    # Opciones de visualización
    parser.add_argument(
        '--display',
        action='store_true',
        help='Mostrar video procesado en tiempo real'
    )
    
    parser.add_argument(
        '--save-video',
        action='store_true',
        help='Guardar video procesado con detecciones'
    )
    
    parser.add_argument(
        '--no-labels',
        action='store_true',
        help='No mostrar etiquetas en las detecciones'
    )
    
    # Optimizaciones
    parser.add_argument(
        '--use-tensorrt',
        action='store_true',
        help='Usar TensorRT para aceleración (Jetson Nano)'
    )
    
    parser.add_argument(
        '--half',
        action='store_true',
        help='Usar precisión FP16 (half precision)'
    )
    
    parser.add_argument(
        '--device',
        type=str,
        default='auto',
        choices=['auto', 'cpu', 'cuda', '0', '1'],
        help='Dispositivo de procesamiento'
    )
    
    # Opciones avanzadas
    parser.add_argument(
        '--skip-frames',
        type=int,
        default=0,
        help='Saltar N frames entre detecciones (0 = procesar todos)'
    )
    
    parser.add_argument(
        '--buffer-size',
        type=int,
        default=60,
        help='Tamaño del buffer para trayectorias'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Modo verbose con información detallada'
    )
    
    return parser.parse_args()


def load_config(config_path):
    """Cargar configuración desde archivo YAML"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        logging.warning(f"Archivo de configuración no encontrado: {config_path}")
        return {}
    except yaml.YAMLError as e:
        logging.error(f"Error parseando configuración YAML: {e}")
        return {}


def initialize_system(args, config):
    """Inicializar todos los componentes del sistema"""
    
    # 1. Detector de vehículos
    detector = VehicleDetector(
        model_path=args.model,
        confidence_threshold=args.confidence,
        iou_threshold=args.iou_threshold,
        input_size=args.input_size,
        device=args.device,
        use_tensorrt=args.use_tensorrt,
        half_precision=args.half,
        config=config.get('detector', {})
    )
    
    # 2. Tracker de vehículos
    tracker = VehicleTracker(
        max_age=config.get('tracker', {}).get('max_age', 30),
        min_hits=config.get('tracker', {}).get('min_hits', 3),
        iou_threshold=config.get('tracker', {}).get('iou_threshold', 0.3),
        buffer_size=args.buffer_size,
        config=config.get('tracker', {})
    )
    
    # 3. Contador bidireccional
    counter = BidirectionalCounter(
        line_position=args.line_y,
        line_type=args.direction,
        config=config.get('counter', {})
    )
    
    # 4. Visualizador
    visualizer = Visualizer(
        show_labels=not args.no_labels,
        show_trajectories=config.get('visualizer', {}).get('show_trajectories', True),
        config=config.get('visualizer', {})
    )
    
    return detector, tracker, counter, visualizer


def process_video(source, detector, tracker, counter, visualizer, args, config):
    """
    Procesar una fuente de video: archivo, webcam o stream de cámara IP.

    Para archivos se conoce el total de frames y se usa una barra de
    progreso; para fuentes en vivo (webcam/RTSP) se procesa de forma
    continua hasta Ctrl+C o hasta presionar 'q' en la ventana de display.
    """

    # Si es un archivo, verificar que existe antes de intentar abrirlo
    is_file = not (
        (isinstance(source, str) and source.isdigit()) or
        (isinstance(source, str) and source.lower().startswith(
            ('rtsp://', 'http://', 'https://')
        ))
    )
    if is_file and not os.path.exists(source):
        logging.error(f"Video no encontrado: {source}")
        sys.exit(1)

    # Abrir fuente (archivo, webcam o stream IP)
    cap, is_live = open_video_source(source)
    if not cap.isOpened():
        logging.error(f"No se pudo abrir la fuente de video: {source}")
        sys.exit(1)

    # Obtener propiedades del video
    fps = int(cap.get(cv2.CAP_PROP_FPS)) or 25
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if not is_live else 0

    tipo_fuente = "EN VIVO (webcam/cámara IP)" if is_live else "archivo"
    logging.info(
        f"Fuente: {source} [{tipo_fuente}] - "
        f"{frame_width}x{frame_height} @ {fps} FPS"
        + (f", {total_frames} frames" if not is_live else "")
    )

    # Configurar escritor de video si es necesario
    video_writer = None
    if args.save_video:
        output_video_path = os.path.join(args.output, 'output_video.mp4')
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        video_writer = cv2.VideoWriter(
            output_video_path,
            fourcc,
            fps,
            (frame_width, frame_height)
        )

    # Inicializar procesador de video
    processor = VideoProcessor(
        detector=detector,
        tracker=tracker,
        counter=counter,
        visualizer=visualizer,
        skip_frames=args.skip_frames,
        config=config.get('processor', {})
    )

    # Configurar línea de conteo si no está especificada
    counter.set_counting_line(
        line_type=args.direction,
        y=args.line_y if args.line_y is not None else frame_height // 2,
        frame_shape=(frame_height, frame_width)
    )

    logging.info("Iniciando procesamiento de video...")

    frame_count = 0
    progress_bar = None
    try:
        if not is_live:
            from tqdm import tqdm
            progress_bar = tqdm(total=total_frames, desc="Procesando", unit="frames")

        while True:
            if is_live:
                ret, frame, cap = read_with_reconnect(cap, source, is_live)
            else:
                ret, frame = cap.read()

            if not ret:
                if is_live:
                    logging.error("Fuente en vivo perdida definitivamente, deteniendo")
                break

            # Procesar frame
            processed_frame, frame_data = processor.process_frame(
                frame,
                frame_count
            )

            # Mostrar en pantalla si se solicita
            if args.display:
                cv2.imshow('Aforo Vehicular', processed_frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    logging.info("Detenido por usuario")
                    break

            # Guardar frame procesado
            if video_writer is not None:
                video_writer.write(processed_frame)

            frame_count += 1
            if progress_bar is not None:
                progress_bar.update(1)

            # Log periódico
            if frame_count % 100 == 0:
                counts = counter.get_counts()
                progreso = f"{frame_count}/{total_frames}" if not is_live else f"{frame_count}"
                logging.info(
                    f"Frame {progreso} - "
                    f"Entrada: {counts['in']}, Salida: {counts['out']}, "
                    f"Total: {counts['total']}"
                )

            # Checkpoint de reportes en fuentes en vivo (para no perder
            # datos si el proceso corre por horas/días)
            if is_live and args.report_interval > 0 and frame_count % args.report_interval == 0:
                generate_reports(counter, tracker, args, config)

        if progress_bar is not None:
            progress_bar.close()

    except KeyboardInterrupt:
        logging.info("\nProcesamiento interrumpido por usuario")

    finally:
        cap.release()
        if video_writer is not None:
            video_writer.release()
        if args.display:
            cv2.destroyAllWindows()

    logging.info(f"Procesamiento completado: {frame_count} frames")

    return frame_count


def generate_reports(counter, tracker, args, config):
    """Generar reportes y estadísticas"""
    
    logging.info("Generando reportes...")
    
    reporter = Reporter(
        output_dir=args.output,
        config=config.get('reporter', {})
    )
    
    # Obtener datos
    counts = counter.get_counts()
    detailed_counts = counter.get_detailed_counts()
    trajectories = tracker.get_all_trajectories()
    
    # Generar reportes
    reporter.save_counts(counts, detailed_counts)
    reporter.save_trajectories(trajectories)
    reporter.generate_statistics(counts, detailed_counts, trajectories)
    reporter.generate_visualizations(trajectories, counter)
    reporter.generate_summary_report(counts, detailed_counts, trajectories)
    
    # Mostrar resumen
    logging.info("=" * 50)
    logging.info("RESUMEN DE CONTEO")
    logging.info("=" * 50)
    logging.info(f"Vehículos entrando: {counts['in']}")
    logging.info(f"Vehículos saliendo: {counts['out']}")
    logging.info(f"Total de vehículos: {counts['total']}")
    logging.info(f"Flujo neto: {counts['net_flow']}")
    logging.info("=" * 50)
    
    # Desglose por tipo
    if detailed_counts:
        logging.info("\nDESGLOSE POR TIPO DE VEHÍCULO:")
        for vehicle_type, type_counts in detailed_counts.items():
            logging.info(
                f"  {vehicle_type.upper()}: "
                f"Entrada={type_counts['in']}, "
                f"Salida={type_counts['out']}, "
                f"Total={type_counts['total']}"
            )
    
    logging.info(f"\nReportes guardados en: {args.output}")


def main():
    """Función principal"""

    # Parsear argumentos
    args = parse_arguments()

    # --source es la forma preferida; --video se mantiene por compatibilidad
    source = args.source or args.video
    if not source:
        print("ERROR: Debes especificar --source (archivo, webcam o URL rtsp/http) "
              "o --video (alias de compatibilidad)")
        sys.exit(1)

    # Crear directorio de salida
    os.makedirs(args.output, exist_ok=True)
    
    # Configurar logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logger = setup_logger(
        log_file=os.path.join(args.output, 'processing.log'),
        level=log_level
    )
    
    # Banner
    logging.info("=" * 60)
    logging.info("  SISTEMA DE AFORO VEHICULAR BIDIRECCIONAL")
    logging.info("  Optimizado para NVIDIA Jetson Nano")
    logging.info("=" * 60)
    logging.info(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Información del dispositivo
    device_info = get_device_info()
    logging.info(f"Dispositivo: {device_info['name']}")
    logging.info(f"CUDA disponible: {device_info['cuda_available']}")
    if device_info['cuda_available']:
        logging.info(f"GPU: {device_info['gpu_name']}")
        logging.info(f"Memoria GPU: {device_info['gpu_memory']}")
    
    # Cargar configuración
    logging.info(f"\nCargando configuración: {args.config}")
    config = load_config(args.config)
    
    # Verificar modelo
    if not os.path.exists(args.model):
        logging.warning(f"Modelo no encontrado: {args.model}")
        logging.info("Descargando modelo YOLOv8n...")
        # El detector descargará automáticamente el modelo
    
    # Inicializar sistema
    logging.info("\nInicializando componentes del sistema...")
    detector, tracker, counter, visualizer = initialize_system(args, config)
    
    # Procesar video
    logging.info("\n" + "=" * 60)
    logging.info("INICIANDO PROCESAMIENTO")
    logging.info("=" * 60)
    
    frame_count = process_video(
        source=source,
        detector=detector,
        tracker=tracker,
        counter=counter,
        visualizer=visualizer,
        args=args,
        config=config
    )
    
    # Generar reportes
    logging.info("\n" + "=" * 60)
    logging.info("GENERANDO REPORTES")
    logging.info("=" * 60)
    
    generate_reports(counter, tracker, args, config)
    
    # Finalizar
    logging.info("\n" + "=" * 60)
    logging.info("PROCESAMIENTO COMPLETADO EXITOSAMENTE")
    logging.info("=" * 60)
    logging.info(f"Frames procesados: {frame_count}")
    logging.info(f"Resultados guardados en: {args.output}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
