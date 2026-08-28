"""
Módulo de generación de reportes y estadísticas
"""

import json
import csv
import os
import logging
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Backend sin GUI
import matplotlib.pyplot as plt
import seaborn as sns
from typing import Dict, List, Tuple, Optional
from datetime import datetime


class Reporter:
    """
    Generador de reportes y análisis
    
    Genera:
    - Archivos JSON con datos detallados
    - CSVs con estadísticas
    - Gráficas y visualizaciones
    - Mapas de calor
    - Reportes de análisis
    """
    
    def __init__(
        self,
        output_dir: str,
        config: Optional[Dict] = None
    ):
        """
        Inicializar generador de reportes
        
        Args:
            output_dir: Directorio de salida
            config: Configuración adicional
        """
        self.output_dir = output_dir
        self.config = config or {}
        
        # Crear directorio si no existe
        os.makedirs(output_dir, exist_ok=True)
        
        # Configurar estilo de gráficas
        sns.set_style("whitegrid")
        plt.rcParams['figure.figsize'] = (12, 6)
        
        logging.info(f"Reporter inicializado: {output_dir}")
    
    def save_counts(
        self,
        counts: Dict,
        detailed_counts: Dict
    ):
        """Guardar conteos en JSON"""
        output_path = os.path.join(self.output_dir, 'counts.json')
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'summary': counts,
            'by_vehicle_type': detailed_counts
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logging.info(f"Conteos guardados: {output_path}")
    
    def save_trajectories(
        self,
        trajectories: Dict[int, List[Tuple[float, float]]]
    ):
        """Guardar trayectorias en JSON"""
        output_path = os.path.join(self.output_dir, 'trajectory_data.json')
        
        # Convertir a formato serializable
        serializable_trajectories = {
            str(track_id): [
                {'x': float(x), 'y': float(y)}
                for x, y in trajectory
            ]
            for track_id, trajectory in trajectories.items()
        }
        
        data = {
            'timestamp': datetime.now().isoformat(),
            'total_tracks': len(trajectories),
            'trajectories': serializable_trajectories
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logging.info(f"Trayectorias guardadas: {output_path}")
    
    def generate_statistics(
        self,
        counts: Dict,
        detailed_counts: Dict,
        trajectories: Dict
    ):
        """Generar archivo CSV con estadísticas"""
        output_path = os.path.join(self.output_dir, 'statistics.csv')
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Encabezados
            writer.writerow(['Métrica', 'Valor'])
            
            # Estadísticas generales
            writer.writerow(['=== RESUMEN GENERAL ===', ''])
            writer.writerow(['Vehículos Entrando', counts['in']])
            writer.writerow(['Vehículos Saliendo', counts['out']])
            writer.writerow(['Total de Vehículos', counts['total']])
            writer.writerow(['Flujo Neto', counts['net_flow']])
            writer.writerow([''])
            
            # Estadísticas por tipo
            writer.writerow(['=== POR TIPO DE VEHÍCULO ===', ''])
            writer.writerow(['Tipo', 'Entrada', 'Salida', 'Total'])
            
            for vehicle_type, type_counts in detailed_counts.items():
                writer.writerow([
                    vehicle_type,
                    type_counts['in'],
                    type_counts['out'],
                    type_counts['total']
                ])
            
            writer.writerow([''])
            
            # Estadísticas de trayectorias
            writer.writerow(['=== TRAYECTORIAS ===', ''])
            writer.writerow(['Total de tracks', len(trajectories)])
            
            if trajectories:
                avg_length = np.mean([len(t) for t in trajectories.values()])
                writer.writerow(['Longitud promedio de trayectoria', f'{avg_length:.2f}'])
        
        logging.info(f"Estadísticas guardadas: {output_path}")
    
    def generate_visualizations(
        self,
        trajectories: Dict,
        counter
    ):
        """Generar visualizaciones (gráficas, mapas de calor)"""
        
        # 1. Gráfica de conteos por tipo
        self._plot_counts_by_type(counter.get_detailed_counts())
        
        # 2. Gráfica de dirección
        self._plot_direction_comparison(counter.get_counts())
        
        # 3. Mapa de calor de trayectorias
        # (requeriría frame_shape, lo haremos simple)
        
        logging.info("Visualizaciones generadas")
    
    def _plot_counts_by_type(self, detailed_counts: Dict):
        """Gráfica de barras de conteos por tipo de vehículo"""
        if not detailed_counts:
            return
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        vehicle_types = list(detailed_counts.keys())
        counts_in = [detailed_counts[vt]['in'] for vt in vehicle_types]
        counts_out = [detailed_counts[vt]['out'] for vt in vehicle_types]
        
        x = np.arange(len(vehicle_types))
        width = 0.35
        
        ax.bar(x - width/2, counts_in, width, label='Entrada', color='green')
        ax.bar(x + width/2, counts_out, width, label='Salida', color='red')
        
        ax.set_xlabel('Tipo de Vehículo')
        ax.set_ylabel('Cantidad')
        ax.set_title('Conteo de Vehículos por Tipo y Dirección')
        ax.set_xticks(x)
        ax.set_xticklabels(vehicle_types)
        ax.legend()
        ax.grid(axis='y', alpha=0.3)
        
        plt.tight_layout()
        output_path = os.path.join(self.output_dir, 'counts_by_type.png')
        plt.savefig(output_path, dpi=150)
        plt.close()
        
        logging.info(f"Gráfica guardada: {output_path}")
    
    def _plot_direction_comparison(self, counts: Dict):
        """Gráfica de comparación de direcciones"""
        if counts.get('total', 0) <= 0:
            logging.info(
                "Sin vehículos contados aún, se omite gráfica de distribución"
            )
            return

        fig, ax = plt.subplots(figsize=(8, 8))

        labels = ['Entrada', 'Salida']
        sizes = [counts['in'], counts['out']]
        colors = ['#90EE90', '#FF6B6B']
        explode = (0.05, 0.05)
        
        ax.pie(
            sizes,
            explode=explode,
            labels=labels,
            colors=colors,
            autopct='%1.1f%%',
            shadow=True,
            startangle=90
        )
        
        ax.axis('equal')
        ax.set_title(
            f'Distribución de Tráfico\nTotal: {counts["total"]} vehículos',
            fontsize=14,
            fontweight='bold'
        )
        
        plt.tight_layout()
        output_path = os.path.join(self.output_dir, 'direction_distribution.png')
        plt.savefig(output_path, dpi=150)
        plt.close()
        
        logging.info(f"Gráfica guardada: {output_path}")
    
    def generate_summary_report(
        self,
        counts: Dict,
        detailed_counts: Dict,
        trajectories: Dict,
        processing_time: Optional[float] = None
    ):
        """Generar reporte de resumen en texto"""
        output_path = os.path.join(self.output_dir, 'summary_report.txt')
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("REPORTE DE AFORO VEHICULAR BIDIRECCIONAL\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"Fecha y Hora: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            # Resumen general
            f.write("RESUMEN GENERAL\n")
            f.write("-" * 60 + "\n")
            f.write(f"  Vehículos Entrando:  {counts['in']:>6}\n")
            f.write(f"  Vehículos Saliendo:  {counts['out']:>6}\n")
            f.write(f"  Total de Vehículos:  {counts['total']:>6}\n")
            f.write(f"  Flujo Neto:          {counts['net_flow']:>6}\n\n")
            
            # Por tipo de vehículo
            if detailed_counts:
                f.write("DESGLOSE POR TIPO DE VEHÍCULO\n")
                f.write("-" * 60 + "\n")
                f.write(f"{'Tipo':<15} {'Entrada':>10} {'Salida':>10} {'Total':>10}\n")
                f.write("-" * 60 + "\n")
                
                for vehicle_type, type_counts in detailed_counts.items():
                    f.write(
                        f"{vehicle_type.upper():<15} "
                        f"{type_counts['in']:>10} "
                        f"{type_counts['out']:>10} "
                        f"{type_counts['total']:>10}\n"
                    )
                f.write("\n")
            
            # Información de trayectorias
            f.write("ANÁLISIS DE TRAYECTORIAS\n")
            f.write("-" * 60 + "\n")
            f.write(f"  Total de tracks registrados: {len(trajectories)}\n")
            
            if trajectories:
                avg_length = np.mean([len(t) for t in trajectories.values()])
                max_length = max([len(t) for t in trajectories.values()])
                min_length = min([len(t) for t in trajectories.values()])
                
                f.write(f"  Longitud promedio:           {avg_length:.2f} puntos\n")
                f.write(f"  Trayectoria más larga:       {max_length} puntos\n")
                f.write(f"  Trayectoria más corta:       {min_length} puntos\n")
            
            f.write("\n")
            
            # Tiempo de procesamiento
            if processing_time:
                f.write("RENDIMIENTO\n")
                f.write("-" * 60 + "\n")
                f.write(f"  Tiempo de procesamiento:     {processing_time:.2f} segundos\n")
            
            f.write("\n" + "=" * 60 + "\n")
        
        logging.info(f"Reporte de resumen guardado: {output_path}")
