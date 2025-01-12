import click
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.crud import crud_user
from app.schemas.user import UserCreate
from app.models.user import UserRole
import sys
import os

# Добавляем путь к корневой директории проекта в PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

@click.group()
def cli():
    """Утилита для управления пользователями"""
    pass

@cli.command()
@click.option('--email', prompt='Email пользователя', help='Email пользователя')
@click.option('--password', prompt=True, hide_input=True, confirmation_prompt=True, help='Пароль пользователя')
@click.option('--role', type=click.Choice(['admin', 'manager', 'user'], case_sensitive=False), 
              prompt='Роль пользователя', help='Роль пользователя')
def create_user(email: str, password: str, role: str):
    """Создать нового пользователя"""
    db = SessionLocal()
    try:
        # Проверяем, существует ли пользователь
        existing_user = crud_user.get_user_by_email(db, email)
        if existing_user:
            click.echo(f"Пользователь с email {email} уже существует")
            return

        # Создаем пользователя
        user_data = UserCreate(
            email=email,
            password=password,
            role=UserRole(role.lower())
        )
        user = crud_user.create_user(db, user_data)
        click.echo(f"Пользователь успешно создан: ID={user.id}, Email={user.email}, Role={user.role}")
    
    except Exception as e:
        click.echo(f"Ошибка при создании пользователя: {str(e)}", err=True)
    finally:
        db.close()

@cli.command()
def list_users():
    """Показать список всех пользователей"""
    db = SessionLocal()
    try:
        users = crud_user.get_users(db)
        if not users:
            click.echo("Пользователи не найдены")
            return

        click.echo("\nСписок пользователей:")
        click.echo("-" * 50)
        for user in users:
            click.echo(f"ID: {user.id}")
            click.echo(f"Email: {user.email}")
            click.echo(f"Роль: {user.role}")
            click.echo("-" * 50)
    
    except Exception as e:
        click.echo(f"Ошибка при получении списка пользователей: {str(e)}", err=True)
    finally:
        db.close()

@cli.command()
def recreate_tables():
    """Пересоздать все таблицы (Внимание: все данные будут удалены!)"""
    if click.confirm('Вы уверены? Все данные будут удалены!'):
        from app.core.database import engine
        from app.models.user import Base as UserBase
        from app.models.document import Base as DocumentBase

        click.echo("Удаление существующих таблиц...")
        UserBase.metadata.drop_all(bind=engine)
        DocumentBase.metadata.drop_all(bind=engine)
        
        click.echo("Создание новых таблиц...")
        UserBase.metadata.create_all(bind=engine)
        DocumentBase.metadata.create_all(bind=engine)
        
        click.echo("Таблицы успешно пересозданы!")

if __name__ == '__main__':
    cli() 