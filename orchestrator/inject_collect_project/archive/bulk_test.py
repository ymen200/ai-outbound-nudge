import csv
from database_manager import Neo4jManager

def run_ingestion():
    manager = Neo4jManager()
    list_to_import = []

    print("--- Phase 1 : Lecture du CSV ---")
    try:
        # Assure-toi que le fichier companies.csv est dans le même dossier
        with open('companies.csv', mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                list_to_import.append(row)
        
        if list_to_import:
            print(f"Extraction terminée. {len(list_to_import)} lignes trouvées.")
            print("--- Phase 2 : Injection dans le Graphe ---")
            manager.bulk_import_companies(list_to_import)
        else:
            print("⚠️ Le fichier CSV est vide.")

    except FileNotFoundError:
        print("❌ Erreur : Crée d'abord le fichier 'companies.csv' avec les colonnes domain,name,siret.")
    except Exception as e:
        print(f"❌ Erreur imprévue : {e}")
    finally:
        manager.close()
        print("--- Processus terminé ---")

if __name__ == "__main__":
    run_ingestion()