from pydantic import BaseModel, EmailStr, Field

class RegisterForm(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)

class LoginForm(BaseModel):
    email: EmailStr
    password: str